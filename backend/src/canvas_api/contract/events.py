"""Server-to-client events on ``WS /api/projects/{id}/events``.

Every message is one JSON object with a ``type`` field. Clients should ignore
types they do not know, so new events can be added without breaking them.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import CompleteModel, NodeId
from .generation import Job, Output


class JobUpdatedEvent(CompleteModel):
    """Sent on every job status or progress change."""

    type: Literal["job.updated"] = "job.updated"
    job: Job


class OutputCreatedEvent(CompleteModel):
    """Sent when a job succeeds, before its final ``job.updated``."""

    type: Literal["output.created"] = "output.created"
    output: Output
    # The node's selected output after this event (the new output).
    node_id: NodeId


ServerEvent = Annotated[JobUpdatedEvent | OutputCreatedEvent, Field(discriminator="type")]
