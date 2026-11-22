"""Jobs: queueing, status changes and recording results."""

from __future__ import annotations

from ..contract import (
    ErrorCode,
    Job,
    JobInput,
    JobStatus,
    MediaKind,
    Node,
    Operation,
    Output,
    Provider,
)
from ..errors import ApiError
from ..ids import new_id
from .base import (
    ACTIVE,
    _not_found,
    _ts,
    now,
)


class _Abandoned(Exception):
    """The job stopped being 'running' before its result was recorded."""


class JobsMixin:
    """Jobs: queueing, status changes and recording results."""

    def get_job(self, job_id: str) -> Job:
        row = self._one("SELECT * FROM jobs WHERE id = ?", job_id)
        if not row:
            raise _not_found("job", job_id)
        return self._job(row)

    def active_job(self, node_id: str) -> Job | None:
        row = self._one(f"SELECT * FROM jobs WHERE node_id = ? AND status IN {ACTIVE}", node_id)
        return self._job(row) if row else None

    def job_ids_with_status(self, status: JobStatus) -> list[str]:
        rows = self._all(
            "SELECT id FROM jobs WHERE status = ? ORDER BY created_at", status.value
        )
        return [r["id"] for r in rows]

    def create_job(
        self, node: Node, provider: Provider, operation: Operation, job_input: JobInput
    ) -> Job:
        job_id = new_id("job")
        with self._tx() as db:
            # Checked inside the transaction so two quick clicks can't both queue.
            busy = db.execute(
                f"SELECT id FROM jobs WHERE node_id = ? AND status IN {ACTIVE}", (node.id,)
            ).fetchone()
            if busy:
                raise ApiError(
                    409,
                    ErrorCode.job_in_progress,
                    f"node {node.id} already has job {busy['id']} in progress",
                    {"job_id": busy["id"]},
                )
            db.execute(
                "INSERT INTO jobs (id, project_id, node_id, status, provider, operation, "
                "input, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    node.project_id,
                    node.id,
                    JobStatus.queued.value,
                    provider.value,
                    operation.value,
                    job_input.model_dump_json(),
                    _ts(now()),
                ),
            )
        return self.get_job(job_id)

    def transition_job(
        self,
        job_id: str,
        status: JobStatus,
        *,
        from_statuses: tuple[JobStatus, ...] = (),
        error: str | None = None,
    ) -> Job | None:
        """Move a job to `status` if it is currently in one of `from_statuses`.

        Returns the updated job, or None when it was not in an allowed state
        (e.g. it was cancelled meanwhile) or no longer exists.
        """
        allowed = tuple(s.value for s in from_statuses) or ACTIVE
        if status == JobStatus.queued:
            stamp = ""  # re-queued for a resume: keep started_at
        elif status == JobStatus.running:
            stamp = ", started_at = COALESCE(started_at, ?)"
        else:
            stamp = ", finished_at = ?"
        values = (status.value, error) + ((_ts(now()),) if stamp else ())
        with self._tx() as db:
            cur = db.execute(
                f"UPDATE jobs SET status = ?, error = ?{stamp} "
                f"WHERE id = ? AND status IN ({','.join('?' * len(allowed))})",
                (*values, job_id, *allowed),
            )
            if cur.rowcount == 0:
                return None
        return self.get_job(job_id)

    def set_provider_task_id(self, job_id: str, task_id: str) -> None:
        with self._tx() as db:
            db.execute("UPDATE jobs SET provider_task_id = ? WHERE id = ?", (task_id, job_id))

    def complete_job(
        self,
        job_id: str,
        *,
        kind: MediaKind,
        text: str | None = None,
        media: tuple[bytes, str, str] | None = None,
        width: int | None = None,
        height: int | None = None,
        duration_s: float | None = None,
    ) -> tuple[Job, Output] | None:
        """Record a successful job: asset file, output, node's selected take.

        `media` is (bytes, mime, file extension). Returns None if the job was
        cancelled or deleted meanwhile; nothing is written then.
        """
        job = self.get_job(job_id)
        if job.status != JobStatus.running:
            return None
        output_id, ts = new_id("out"), _ts(now())
        asset_id, path = None, None
        if media is not None:
            data, mime, ext = media
            asset_id = new_id("ast")
            path = self.assets_dir / f"{asset_id}.{ext}"
            path.write_bytes(data)
        try:
            with self._tx() as db:
                row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
                if row is None or row["status"] != JobStatus.running.value:
                    raise _Abandoned
                if media is not None:
                    db.execute(
                        "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            asset_id,
                            job.project_id,
                            kind.value,
                            mime,
                            path.name,
                            len(data),
                            width,
                            height,
                            duration_s,
                            ts,
                        ),
                    )
                db.execute(
                    "INSERT INTO outputs (id, node_id, job_id, kind, text, asset_id, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        output_id,
                        job.node_id,
                        job_id,
                        kind.value,
                        text,
                        asset_id,
                        ts,
                    ),
                )
                db.execute(
                    "UPDATE nodes SET selected_output_id = ? WHERE id = ?",
                    (output_id, job.node_id),
                )
                db.execute(
                    "UPDATE jobs SET status = ?, output_id = ?, progress = 1, "
                    "finished_at = ? WHERE id = ?",
                    (JobStatus.succeeded.value, output_id, ts, job_id),
                )
        except _Abandoned:
            if path:
                path.unlink(missing_ok=True)
            return None
        except BaseException:
            if path:
                path.unlink(missing_ok=True)
            raise
        return self.get_job(job_id), self.get_output(output_id)
