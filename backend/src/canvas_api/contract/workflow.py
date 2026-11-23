"""Workflows: designed once per collection, run per project.

A **workflow** (designed in a collection, see contract/collections.py) is an
ordered list of steps; a step is a name, the kind of node it makes, and how its results
are used (``OutputUse``):

- ``independent``: its nodes get IDs ("<key>_<n>") and don't flow anywhere
  by themselves; any later run prompt (or node prompt) uses one by
  mentioning its ID, e.g. "a video of characters_2 dancing".
- ``one_to_one``: its nodes have no ID (nothing else may refer to them);
  node *i* feeds node *i* of the next step, which makes exactly as many.

Names are the user's own text, sent and shown as written in every language.

A project runs on its collection's active workflow (``Project.workflow``).
In a project, each step is **run** with a prompt and a count (after a
one-to-one step, the count is that step's number of nodes): the prompt, the
project instruction, the nodes it mentions and any one-to-one inputs go to a
text model, which writes that many results (a text step) or prompts (an
image or video step, then generated). An image or video step fed one-to-one
by text uses each text as its prompt directly. Running a step again replaces
its nodes.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .common import (
    CompleteModel,
    ContractModel,
    Language,
    MediaKind,
    NodeId,
    OutputId,
    Timestamp,
)

# The most nodes one run of a step may make.
MAX_ITEMS = 20

STEP_KEY = r"^[a-z][a-z0-9_]{0,39}$"


class OutputUse(StrEnum):
    # Its nodes get IDs; later steps use them by mentioning the IDs.
    independent = "independent"
    # Its nodes have no ID; node i feeds node i of the next step.
    one_to_one = "one_to_one"


class WorkflowStep(CompleteModel):
    # Stable identity (node IDs are "<key>_<n>"), set by the designer.
    key: str = Field(pattern=STEP_KEY)
    name: str = Field(min_length=1, max_length=80)
    kind: MediaKind
    output: OutputUse = OutputUse.independent
    # How many a run makes unless the project says otherwise (the run form
    # starts with it). Null: no default, the project must say. Ignored after a
    # one-to-one step (there, the step before decides).
    count: int | None = Field(default=None, ge=1, le=MAX_ITEMS)


class WorkflowDefinition(CompleteModel):
    id: str
    version: int = 1
    name: str = Field(min_length=1, max_length=80)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _unique_keys(self) -> WorkflowDefinition:
        keys = [s.key for s in self.steps]
        if len(set(keys)) != len(keys):
            raise ValueError("two steps have the same key")
        if self.steps[-1].output == OutputUse.one_to_one:
            raise ValueError("the last step has no next step to feed one-to-one")
        return self


# --- per project: runs -----------------------------------------------------------------


class RunStatus(StrEnum):
    #: The model is writing the results; the step's old nodes are still there.
    running = "running"
    #: The step's nodes are the results of this run.
    done = "done"
    #: The run failed (``error`` says why); the old nodes are untouched.
    failed = "failed"


class StepRun(CompleteModel):
    """The last run of a step in a project: what it was asked for, and how
    it went. A run happens in the background: ``runStep`` answers with the
    run ``running``; poll the graph until it is ``done`` or ``failed``."""

    step: str
    prompt: str
    count: int
    status: RunStatus
    error: str | None = None
    updated_at: Timestamp


class StepRunRequest(ContractModel):
    """``prompt`` may be empty only for an image or video step fed one-to-one
    by text (each text is the prompt). ``count`` is ignored after a
    one-to-one step, and required otherwise."""

    prompt: str = Field(default="", max_length=4000)
    count: int | None = Field(default=None, ge=1, le=MAX_ITEMS)


# --- settings, approval, takes, chat ---------------------------------------------------


class AppSettings(CompleteModel):
    """App-wide settings, chosen on the landing page."""

    language: Language = Language.en


class AppSettingsUpdate(ContractModel):
    language: Language


class TakeCreate(ContractModel):
    """A text take written by hand (or applied from elsewhere)."""

    text: str = Field(min_length=1, max_length=100_000)


class ChatRole(StrEnum):
    user = "user"
    assistant = "assistant"


class ChatMessage(CompleteModel):
    """One message of a node's chat. An assistant message may carry a
    ``proposal``: a complete new version of the node's text, which
    ``applyProposal`` turns into a take."""

    id: str = Field(pattern=r"^msg_[A-Za-z0-9]+$")
    node_id: NodeId
    role: ChatRole
    text: str
    proposal: str | None = None
    # The take made from the proposal, once applied.
    applied_output_id: OutputId | None = None
    created_at: Timestamp


class ChatRequest(ContractModel):
    text: str = Field(min_length=1, max_length=20_000)
