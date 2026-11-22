"""Projects: one canvas each."""

from __future__ import annotations

from pydantic import Field

from .common import CompleteModel, ContractModel, ProjectId, Timestamp, Viewport
from .instructions import MAX_INSTRUCTION_CHARS
from .workflow import WorkflowDefinition


class Project(CompleteModel):
    id: ProjectId
    name: str
    viewport: Viewport
    # The project's own instruction (see contract/instructions.py); starts as
    # a copy of the global instruction.
    instruction: str
    # The project's own copy of its workflow (see contract/workflow.py).
    workflow: WorkflowDefinition
    created_at: Timestamp
    updated_at: Timestamp


class ProjectCreate(ContractModel):
    name: str = Field(default="Untitled", min_length=1, max_length=200)
    # Omitted (or null): copy the global instruction.
    instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)
    # The workflow template to copy; omitted (or null): the default one.
    workflow_template_id: str | None = None


class ProjectUpdate(ContractModel):
    """Partial update: omitted fields are left as they are."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    viewport: Viewport | None = None
    instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)
