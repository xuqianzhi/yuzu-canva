from __future__ import annotations

from fastapi import APIRouter, WebSocket

from ..contract import ProjectId

router = APIRouter(tags=["events"])


@router.websocket("/projects/{project_id}/events")
async def project_events(websocket: WebSocket, project_id: ProjectId) -> None:
    """Stream of ServerEvent JSON messages for one project.

    Not in OpenAPI (it cannot describe WebSockets); the message types are
    added to the schema's components by app.py instead.
    """
    await websocket.accept()
    await websocket.close(code=1011, reason="events are not implemented yet")
