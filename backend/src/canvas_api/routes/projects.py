from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.concurrency import run_in_threadpool

from ..contract import (
    Project,
    ProjectCreate,
    ProjectGraph,
    ProjectId,
    ProjectSummary,
    ProjectUpdate,
    RestoreRequest,
    RestoreResult,
)
from ..deps import FilesDep, StoreDep, UserDep, WorkerDep
from ..errors import responses
from ..files import delete_all

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", operation_id="listProjects", responses=responses())
def list_projects(store: StoreDep, user: UserDep) -> list[ProjectSummary]:
    """Your projects, most recently updated first, with counts and a cover."""
    return store.list_project_summaries(user.id)


@router.post("", status_code=201, operation_id="createProject", responses=responses())
def create_project(body: ProjectCreate, store: StoreDep, user: UserDep) -> Project:
    """Create a project. It starts with one uploaded node per global asset,
    down the left side of its canvas. ``workflow_template_id`` must be one
    of yours (404 otherwise); by default, your default workflow."""
    return store.create_project(user.id, body)


@router.get("/{project_id}", operation_id="getProjectGraph", responses=responses(404))
def get_project_graph(project_id: ProjectId, store: StoreDep) -> ProjectGraph:
    """The whole canvas: project, nodes, edges, outputs and active jobs."""
    return store.get_graph(project_id)


@router.patch("/{project_id}", operation_id="updateProject", responses=responses(404))
def update_project(project_id: ProjectId, body: ProjectUpdate, store: StoreDep) -> Project:
    return store.update_project(project_id, body)


@router.delete(
    "/{project_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteProject",
    responses=responses(404),
)
async def delete_project(
    project_id: ProjectId, store: StoreDep, worker: WorkerDep, files: FilesDep
) -> None:
    """Deletes the project with its nodes, edges, jobs, outputs and assets."""
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
