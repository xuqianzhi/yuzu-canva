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
    # The project's own instruction (see contract/instructions.py).
    instruction: str
    # Its collection's instruction, read live (edited in the collection).
    collection_instruction: str = ""
    # Its collection's active workflow (see contract/collections.py).
    workflow: WorkflowDefinition
    # Its collection's settings for running image / video steps straight
    # through (``Collection.direct_image`` / ``direct_video``), read live.
    direct_image: bool = False
    direct_video: bool = False
    created_at: Timestamp
    updated_at: Timestamp


class ProjectCreate(ContractModel):
    name: str = Field(default="Untitled", min_length=1, max_length=200)
    # The project's own instruction (omitted: none). The collection's applies
    # anyway; it isn't copied.
    instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)


class ProjectUpdate(ContractModel):
    """Partial update: omitted fields are left as they are."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    viewport: Viewport | None = None
    instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)
