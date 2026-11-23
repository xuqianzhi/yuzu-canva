"""Projects: one canvas each."""

from __future__ import annotations

from pydantic import Field

from .common import CompleteModel, ContractModel, ProjectId, Timestamp, Viewport
from .instructions import MAX_INSTRUCTION_CHARS
from .workflow import WorkflowDefinition


class Project(CompleteModel):
    id: ProjectId
    collection_id: str = Field(pattern=r"^col_[A-Za-z0-9]+$")
    name: str
    viewport: Viewport
    # The project's own instruction (see contract/instructions.py); starts as
    # a copy of its collection's.
    instruction: str
    # Its collection's active workflow (see contract/collections.py).
    workflow: WorkflowDefinition
    created_at: Timestamp
    updated_at: Timestamp


class ProjectCreate(ContractModel):
    name: str = Field(default="Untitled", min_length=1, max_length=200)
    # Omitted (or null): copy the collection's instruction.
    instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)


class ProjectUpdate(ContractModel):
    """Partial update: omitted fields are left as they are."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    viewport: Viewport | None = None
    instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)
