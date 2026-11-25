from __future__ import annotations

from fastapi import APIRouter, Response

from ..contract import (
    ErrorCode,
    GenerateRequest,
    Job,
    Node,
    NodeCreate,
    NodeId,
    NodeMoves,
    NodeSource,
    NodeUpdate,
    Output,
    ProjectId,
)
from ..deps import SpendingDep, StoreDep, UserDep, WorkerDep
from ..errors import ApiError, responses
from ..jobs.queue import queue_generation

router = APIRouter(tags=["nodes"])


@router.post(
    "/projects/{project_id}/nodes",
    status_code=201,
    operation_id="createNode",
    responses=responses(404),
)
def create_node(project_id: ProjectId, body: NodeCreate, store: StoreDep) -> Node:
    return store.create_node(project_id, body)


@router.patch(
    "/projects/{project_id}/positions",
    operation_id="moveNodes",
    responses=responses(404, 409),
)
def move_nodes(project_id: ProjectId, body: NodeMoves, store: StoreDep) -> list[Node]:
    """Move several nodes at once, in one transaction (all of them, or 404
    if any isn't in this project): for tidying the canvas onto a grid
    without a request per node. Returns the moved nodes."""
    return store.move_nodes(project_id, body.moves)


@router.patch("/nodes/{node_id}", operation_id="updateNode", responses=responses(404))
def update_node(node_id: NodeId, body: NodeUpdate, store: StoreDep) -> Node:
    """Move, resize, rename, edit the prompt or params, or pick a take.

    ``selected_output_id`` must be one of this node's outputs. A name must be
    unique in the project (409 ``duplicate_name``); null or blank removes it.
    """
    return store.update_node(node_id, body)


@router.delete(
    "/nodes/{node_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteNode",
    responses=responses(404),
)
async def delete_node(node_id: NodeId, store: StoreDep, worker: WorkerDep) -> None:
    """Deletes the node and every edge touching it; cancels its running jobs.

    The delete is soft: ``restoreDeleted`` brings the node back with its
    takes (undo) until it is purged a day later. Downstream nodes keep their
    own outputs; prompts that mention its ID keep the text (unlinked).
    """
    if store.get_node(node_id).workflow_step:
        raise ApiError(
            409,
            ErrorCode.workflow_locked,
            "a workflow node belongs to its step and can't be deleted",
            {"node_id": node_id},
        )
    _, active_jobs = store.delete_node(node_id)
    for job_id in active_jobs:
        worker.abort(job_id)


@router.get(
    "/nodes/{node_id}/outputs", operation_id="listNodeOutputs", responses=responses(404)
)
def list_node_outputs(node_id: NodeId, store: StoreDep) -> list[Output]:
    """Every take of the node, newest first."""
    return store.list_outputs(node_id)


@router.post(
    "/nodes/{node_id}/generate",
    status_code=202,
    operation_id="generateNode",
    responses=responses(404, 409),
)
async def generate_node(
    node_id: NodeId,
    store: StoreDep,
    worker: WorkerDep,
    spending: SpendingDep,
    user: UserDep,
    body: GenerateRequest | None = None,
) -> Job:
    """Queue a generation from the node's saved prompt, params and references.

    Each reference resolves to the source node's ``selected_output_id``.
    Fails (409) with ``missing_ref_output``, ``unsupported_ref``,
    ``too_many_refs``, ``job_in_progress`` or
    ``not_generatable`` (an uploaded node); 429 ``quota_exceeded`` past a
    limit; 503 ``generation_off``. Poll ``getJob`` (or the graph) for
    progress.
    """
    node = store.get_node(node_id)
    if node.source == NodeSource.upload:
        raise ApiError(
            409, ErrorCode.not_generatable, "an uploaded node holds a file; it can't generate"
        )
    if active := store.active_job(node_id):
        raise ApiError(
            409,
            ErrorCode.job_in_progress,
            f"node {node_id} already has job {active.id} in progress",
            {"job_id": active.id},
        )
    return queue_generation(store, worker, node, user.id, spending)
