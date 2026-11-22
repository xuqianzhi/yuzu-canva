"""Runs queued jobs on the event loop.

Jobs live in the database, so the queue survives restarts: queued jobs are
re-queued on start, and jobs that were running when the process died are
marked failed (their provider call is lost).
"""

from __future__ import annotations

import asyncio
import logging

from ..contract import ErrorCode, Job, JobStatus, Operation
from ..errors import ApiError
from ..providers.base import GenerationRequest, Generator, ProviderError, RefFile
from ..store import Store

log = logging.getLogger(__name__)


class Worker:
    def __init__(
        self, store: Store, generators: dict[Operation, Generator], concurrency: int = 4
    ) -> None:
        self._store = store
        self._generators = generators
        self._concurrency = max(1, concurrency)
        self._queue: asyncio.Queue[str] | None = None
        self._consumers: list[asyncio.Task] = []
        self._running: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        self._queue = asyncio.Queue()
        for job_id in self._store.job_ids_with_status(JobStatus.running):
            job = self._store.get_job(job_id)
            generator = self._generators.get(job.operation)
            if job.provider_task_id and getattr(generator, "resumable", False):
                # The provider still has it: pick up where we left off.
                self._store.transition_job(
                    job_id, JobStatus.queued, from_statuses=(JobStatus.running,)
                )
                continue
            self._store.transition_job(
                job_id,
                JobStatus.failed,
                from_statuses=(JobStatus.running,),
                error="interrupted by a server restart; generate again",
            )
        for job_id in self._store.job_ids_with_status(JobStatus.queued):
            self._queue.put_nowait(job_id)
        self._consumers = [
            asyncio.create_task(self._consume(), name=f"job-worker-{i}")
            for i in range(self._concurrency)
        ]

    async def stop(self) -> None:
        for task in self._consumers:
            task.cancel()
        await asyncio.gather(*self._consumers, return_exceptions=True)
        self._consumers = []

    def enqueue(self, job_id: str) -> None:
        """Call from the event loop (async routes)."""
        assert self._queue is not None, "worker not started"
        self._queue.put_nowait(job_id)

    def cancel(self, job_id: str) -> Job:
        job = self._store.get_job(job_id)
        updated = self._store.transition_job(
            job_id, JobStatus.canceled, from_statuses=(JobStatus.queued, JobStatus.running)
        )
        if updated is None:
            job = self._store.get_job(job_id)
            raise ApiError(
                409, ErrorCode.job_finished, f"job {job_id} already {job.status.value}"
            )
        self.abort(job_id)
        return updated

    def abort(self, job_id: str) -> None:
        """Stop a running provider call without touching the job row."""
        task = self._running.get(job_id)
        if task is not None:
            task.cancel()

    async def _consume(self) -> None:
        assert self._queue is not None
        while True:
            job_id = await self._queue.get()
            try:
                await self._run(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job %s crashed the worker", job_id)

    async def _run(self, job_id: str) -> None:
        job = self._store.transition_job(
            job_id, JobStatus.running, from_statuses=(JobStatus.queued,)
        )
        if job is None:  # cancelled or deleted while queued
            return
        try:
            generator = self._generators[job.operation]
            request = self._request(job)
        except Exception as exc:  # noqa: BLE001 - reported on the job
            self._fail(job_id, f"cannot start: {exc}")
            return

        task = asyncio.create_task(generator.run(request))
        self._running[job_id] = task
        try:
            result = await task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():  # the worker itself is stopping
                raise
            return  # the job was cancelled; cancel() already updated it
        except ProviderError as exc:
            self._fail(job_id, str(exc))
            return
        except Exception as exc:
            log.exception("job %s failed", job_id)
            self._fail(job_id, f"internal error: {type(exc).__name__}: {exc}")
            return
        finally:
            self._running.pop(job_id, None)

        media = None
        if result.data is not None:
            media = (
                result.data,
                result.mime or "application/octet-stream",
                result.ext or "bin",
            )
        self._store.complete_job(
            job_id,
            kind=result.kind,
            text=result.text,
            media=media,
            width=result.width,
            height=result.height,
            duration_s=result.duration_s,
        )

    def _request(self, job: Job) -> GenerationRequest:
        files = []
        for ref in job.input.refs:
            output = self._store.get_output(ref.output_id)
            if output.asset is not None:
                asset, path = self._store.asset_file(output.asset.id)
                files.append(
                    RefFile(node_id=ref.node_id, kind=asset.kind, path=path, mime=asset.mime)
                )
        return GenerationRequest(
            operation=job.operation,
            prompt=job.input.prompt,
            params=job.input.params,
            files=files,
            system=job.input.system,
            language=job.input.language,
            resume_task_id=job.provider_task_id,
            on_submitted=lambda task_id: self._store.set_provider_task_id(job.id, task_id),
        )

    def _fail(self, job_id: str, message: str) -> None:
        self._store.transition_job(
            job_id, JobStatus.failed, from_statuses=(JobStatus.running,), error=message
        )
