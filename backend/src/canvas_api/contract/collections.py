"""Collections: shared folders of projects that all run on one workflow.

A **collection** (say "Anime" or "Educational") holds projects, which are
still one video each, plus what its projects share:

- **workflows**: any number, of which exactly one is **active**. Every
  project in the collection runs on the active one; switching it (or
  editing it) applies to every project. A project keeps its step results by
  step key, so steps missing from the active workflow are hidden, not
  deleted.
- an **instruction**: new projects start with a copy of it.
- **assets**: named images and videos; each new project starts with them
  as uploaded nodes (its own copies).

**Members.** The person who creates a collection is its **owner**; they
invite **editors** by email, who accept before they get in. Editors can do
everything except delete projects or the collection and manage members.
Others get 404 for anything in it; editors get 403 ``forbidden`` for
owner-only actions.

**Paying.** The owner pays for everything generated in their collection:
usage counts against the owner's daily limits, and the owner can also
limit each editor per day (``EditorLimits``).

**One editor per project.** Changing a project needs its **lock**
(``ProjectLock``), held by one browser tab at a time; see ``lockProject``.
Collection settings use a version check instead (``CollectionUpdate.version``,
``WorkflowSave.base_version``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from .common import CompleteModel, ContractModel, MediaKind, ProjectId, Timestamp
from .instructions import MAX_INSTRUCTION_CHARS
from .users import UsageCounts
from .workflow import WorkflowDefinition

CollectionId = Annotated[str, Field(pattern=r"^col_[A-Za-z0-9]+$", examples=["col_k2m9"])]
WorkflowId = Annotated[str, Field(pattern=r"^wfl_[A-Za-z0-9]+$", examples=["wfl_a7x2"])]
InviteId = Annotated[str, Field(pattern=r"^inv_[A-Za-z0-9]+$", examples=["inv_q8w1"])]
CollectionAssetId = Annotated[str, Field(pattern=r"^cas_[A-Za-z0-9]+$", examples=["cas_k2m9"])]

# The header a browser tab sends with every change to a project: its own
# random ID, so the server knows which tab holds the project's lock.
EDIT_SESSION_HEADER = "X-Edit-Session"
# How long a lock lasts unless renewed (the app renews it every 20 s).
LOCK_SECONDS = 60
# How long an invite waits to be accepted.
INVITE_DAYS = 30

# Where new projects put the nodes made from collection assets (canvas
# units): a column down the left, clear of the menu bar, one node per step.
ASSET_NODE_X = 120
ASSET_NODE_Y = 60
ASSET_NODE_STEP = 500


class Role(StrEnum):
    owner = "owner"
    editor = "editor"


class EditorLimits(CompleteModel):
    """What an editor may generate per day (UTC) in one collection, paid by
    the owner. Null: no limit of its own (the owner's daily limits still
    apply to everything together); 0: none of that kind."""

    text: int | None = Field(default=None, ge=0)
    image: int | None = Field(default=None, ge=0)
    video: int | None = Field(default=None, ge=0)


class Collection(CompleteModel):
    id: CollectionId
    name: str
    instruction: str
    active_workflow_id: WorkflowId
    # Goes up by one with every change of name or instruction; send it back
    # with an update (409 ``edit_conflict`` if someone else saved first).
    version: int
    your_role: Role
    owner_email: str
    # Who saved the name or instruction last (null: nobody since creating it).
    updated_by_email: str | None = None
    created_at: Timestamp
    updated_at: Timestamp


class CollectionSummary(Collection):
    """A collection as listed on the landing page."""

    project_count: int = 0
    member_count: int = 0


class CollectionCreate(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    instruction: str = Field(default="", max_length=MAX_INSTRUCTION_CHARS)
    # Its first (active) workflow; omitted: the built-in one.
    workflow: WorkflowDefinition | None = None


class CollectionUpdate(ContractModel):
    """Partial update; ``version`` is the one you last read."""

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)


# --- members and invites ------------------------------------------------------------


class Member(CompleteModel):
    user_id: str
    email: str
    role: Role
    # The owner's are always null (no limits of their own here).
    limits: EditorLimits
    # What this member generated in this collection today (UTC).
    used_today: UsageCounts
    joined_at: Timestamp


class MemberUpdate(ContractModel):
    limits: EditorLimits


class Invite(CompleteModel):
    """An invite waiting for its person to accept it."""

    id: InviteId
    email: str
    limits: EditorLimits
    invited_by_email: str
    created_at: Timestamp
    expires_at: Timestamp


class InviteCreate(ContractModel):
    # Spaces around it are ignored; it's matched without regard to case.
    email: str = Field(min_length=3, max_length=320, pattern=r"^\s*[^@\s]+@[^@\s]+\s*$")
    limits: EditorLimits = Field(default_factory=EditorLimits)


class Invitation(CompleteModel):
    """An invite to you, as you see it."""

    id: InviteId
    collection_id: CollectionId
    collection_name: str
    invited_by_email: str
    created_at: Timestamp
    expires_at: Timestamp


# --- workflows ---------------------------------------------------------------------


class CollectionWorkflow(CompleteModel):
    id: WorkflowId
    collection_id: CollectionId
    # ``definition.version`` goes up by one with every save.
    definition: WorkflowDefinition
    # Whether this is the one the collection's projects run on.
    active: bool
    updated_by_email: str | None = None
    created_at: Timestamp
    updated_at: Timestamp


class WorkflowSave(ContractModel):
    """Create or replace a workflow (``definition.id`` and ``version`` are
    set by the server)."""

    definition: WorkflowDefinition
    # When replacing: the ``definition.version`` you edited. If someone saved
    # since, the save is refused (409 ``edit_conflict``). Omitted: no check.
    base_version: int | None = None


# --- assets ------------------------------------------------------------------------


class CollectionAsset(CompleteModel):
    id: CollectionAssetId
    collection_id: CollectionId
    # Required, unique in the collection (ignoring case and spacing); it
    # becomes the node's name in each new project.
    name: str
    kind: MediaKind
    mime: str
    # Relative to the API origin, e.g. "/api/collection-assets/cas_k2m9/content?...".
    url: str
    bytes: int = Field(ge=0)
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    created_at: Timestamp


class CollectionAssetUpdate(ContractModel):
    name: str = Field(min_length=1, max_length=80)


# --- the project lock --------------------------------------------------------------


class ProjectLock(CompleteModel):
    """Who may change a project right now, as seen by the asking tab."""

    project_id: ProjectId
    # This tab holds it: it may make changes (until ``expires_at``).
    held: bool
    # Whoever holds it, if anyone (null: free).
    holder_email: str | None = None
    # The holder is you, in another tab or on another device.
    holder_is_you: bool = False
    expires_at: Timestamp | None = None


class LockRequest(ContractModel):
    # Take the lock from your own other tab (never from someone else).
    take_over: bool = False
