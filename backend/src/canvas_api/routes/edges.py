from __future__ import annotations

from fastapi import APIRouter, Response

from ..contract import Edge, EdgeCreate, EdgeId, ErrorCode, ProjectId
from ..deps import StoreDep
from ..domain.graph import check_new_edge
from ..errors import ApiError, responses

router = APIRouter(tags=["edges"])


@router.post(
    "/projects/{project_id}/edges",
    status_code=201,
    operation_id="createEdge",
    responses=responses(404, 409),
)
def create_edge(project_id: ProjectId, body: EdgeCreate, store: StoreDep) -> Edge:
    """Make the target node reference the source node (it needs an ID).

    This appends the source's ID to the target's prompt, since links exist
    exactly when the prompt mentions the source.

    Fails (409) with ``self_reference``, ``duplicate_edge`` or ``cycle``.
    Both nodes must be in the project (else 404). Kind compatibility is
    checked at generate time, not here, since a node's kind can change.
    """
    store.get_project(project_id)
    for node_id in (body.source_node_id, body.target_node_id):
        if store.get_node(node_id).project_id != project_id:
            raise ApiError(
                404,
                ErrorCode.not_found,
                f"node {node_id} is not in project {project_id}",
                {"id": node_id},
            )
    edges = store.project_edges(project_id)
    source = store.get_node(body.source_node_id)
    if not source.name:
        raise ApiError(
            409,
            ErrorCode.no_id,
            "give this node an ID first: nothing can refer to a node without one",
            {"node_id": source.id},
        )
    check_new_edge(edges, body)
    # Links follow the prompt: this mentions the source there.
    return store.link_by_mention(body.source_node_id, body.target_node_id)


@router.delete(
    "/edges/{edge_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteEdge",
    responses=responses(404),
)
def delete_edge(edge_id: EdgeId, store: StoreDep) -> None:
    """Soft delete: ``restoreDeleted`` can bring it back (undo). Workflow
    edges can't be deleted (409 ``workflow_locked``)."""
    if any(e.id == edge_id and e.workflow for e in store.edge_by_id(edge_id)):
        raise ApiError(409, ErrorCode.workflow_locked, "workflow connections can't be deleted")
    store.delete_edge(edge_id)
