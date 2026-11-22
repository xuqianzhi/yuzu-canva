from __future__ import annotations

from fastapi import APIRouter

from ..contract import Job, JobId
from ..deps import StoreDep, WorkerDep
from ..errors import responses

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", operation_id="getJob", responses=responses(404))
def get_job(job_id: JobId, store: StoreDep) -> Job:
    return store.get_job(job_id)


@router.post("/{job_id}/cancel", operation_id="cancelJob", responses=responses(404, 409))
async def cancel_job(job_id: JobId, worker: WorkerDep) -> Job:
    """Cancel a queued or running job. Fails (409) with ``job_finished``."""
    return worker.cancel(job_id)
