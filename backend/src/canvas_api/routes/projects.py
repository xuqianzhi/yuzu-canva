from __future__ import annotations

from fastapi import APIRouter, Response

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
from ..deps import StoreDep, WorkerDep, remove_files
from ..errors import responses

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", operation_id="listProjects", responses=responses())
def list_projects(store: StoreDep) -> list[ProjectSummary]:
    """All projects, most recently updated first, with counts and a cover."""
    return store.list_project_summaries()


@router.post("", status_code=201, operation_id="createProject", responses=responses())
def create_project(body: ProjectCreate, store: StoreDep) -> Project:
    """Create a project. It starts with one uploaded node per global asset,
    down the left side of its canvas."""
    return store.create_project(body)


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
async def delete_project(project_id: ProjectId, store: StoreDep, worker: WorkerDep) -> None:
    """Deletes the project with its nodes, edges, jobs, outputs and assets."""
    files, active_jobs = store.delete_project(project_id)
    for job_id in active_jobs:
        worker.abort(job_id)
    remove_files(files)


@router.post("/{project_id}/restore", operation_id="restoreDeleted", responses=responses(404))
def restore_deleted(
    project_id: ProjectId, body: RestoreRequest, store: StoreDep
) -> RestoreResult:
    """Undo deletes: bring back soft-deleted nodes (with their takes) and edges.

    Deleted items are kept for a day, then purged when the API starts.
    """
    nodes, edges, outputs = store.restore(project_id, body.node_ids, body.edge_ids)
    return RestoreResult(nodes=nodes, edges=edges, outputs=outputs)
