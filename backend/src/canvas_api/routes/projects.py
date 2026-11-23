from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from fastapi.concurrency import run_in_threadpool

from ..contract import (
    EDIT_SESSION_HEADER,
    LockRequest,
    Project,
    ProjectGraph,
    ProjectId,
    ProjectLock,
    ProjectUpdate,
    RestoreRequest,
    RestoreResult,
)
from ..deps import FilesDep, StoreDep, UserDep, WorkerDep, no_edit_lock, require_owner
from ..errors import responses
from ..files import delete_all

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("/{project_id}", operation_id="getProjectGraph", responses=responses(404))
def get_project_graph(project_id: ProjectId, store: StoreDep) -> ProjectGraph:
    """The whole canvas: project, nodes, edges, outputs and active jobs."""
    return store.get_graph(project_id)


@router.patch("/{project_id}", operation_id="updateProject", responses=responses(404))
def update_project(project_id: ProjectId, body: ProjectUpdate, store: StoreDep) -> Project:
    return store.update_project(project_id, body)


@no_edit_lock
@router.delete(
    "/{project_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteProject",
    responses=responses(403, 404),
    dependencies=[Depends(require_owner)],
)
async def delete_project(
    project_id: ProjectId, store: StoreDep, worker: WorkerDep, files: FilesDep
) -> None:
    """Owner only; even while someone is editing it (their next request
    gets 404). Deletes the project with its nodes, edges, jobs, outputs,
    assets and their files."""
    keys, active_jobs = await run_in_threadpool(store.delete_project, project_id)
    for job_id in active_jobs:
        worker.abort(job_id)
    await run_in_threadpool(delete_all, files, keys)


@router.post("/{project_id}/restore", operation_id="restoreDeleted", responses=responses(404))
def restore_deleted(
    project_id: ProjectId, body: RestoreRequest, store: StoreDep
) -> RestoreResult:
    """Undo deletes: bring back soft-deleted nodes (with their takes) and edges.

    Deleted items are kept for a day, then purged when the API starts.
    """
    nodes, edges, outputs = store.restore(project_id, body.node_ids, body.edge_ids)
    return RestoreResult(nodes=nodes, edges=edges, outputs=outputs)


# --- the edit lock -------------------------------------------------------------------

EditSession = Annotated[
    str | None,
    Header(
        alias=EDIT_SESSION_HEADER,
        max_length=100,
        description="This browser tab's own random ID, the same for all its requests.",
    ),
]


@router.get("/{project_id}/lock", operation_id="getProjectLock", responses=responses(404))
def get_project_lock(
    project_id: ProjectId, store: StoreDep, user: UserDep, session: EditSession = None
) -> ProjectLock:
    """Who holds the project's lock right now, as seen by this tab."""
    return store.lock_status(project_id, user.id, session)


@no_edit_lock
@router.post("/{project_id}/lock", operation_id="lockProject", responses=responses(404, 409))
def lock_project(
    project_id: ProjectId,
    store: StoreDep,
    user: UserDep,
    session: EditSession = None,
    body: LockRequest | None = None,
) -> ProjectLock:
    """Take or renew the lock for this tab: only the tab holding it may
    change the project. It lasts 60 s; renew it (call again) every 20 s
    while the project is open, and release it on leaving.

    409 ``project_locked`` while someone else holds it (``context``:
    ``holder_email``, ``holder_is_you``). With ``take_over``, you take it
    from your own other tab (never from someone else). Any change to the
    project also takes the lock if it's free."""
    return store.acquire_lock(project_id, user.id, session, (body or LockRequest()).take_over)


@no_edit_lock
@router.delete(
    "/{project_id}/lock",
    status_code=204,
    response_class=Response,
    operation_id="unlockProject",
    responses=responses(404),
)
def unlock_project(
    project_id: ProjectId, store: StoreDep, user: UserDep, session: EditSession = None
) -> None:
    """Release the lock, if this tab holds it."""
    store.release_lock(project_id, user.id, session)
