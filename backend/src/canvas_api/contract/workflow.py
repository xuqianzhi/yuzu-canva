"""Workflows: designed once per collection, run per project.

A **workflow** (designed in a collection, see contract/collections.py) is an
ordered list of steps; a step is a name and the kind of node it makes. Its
nodes get IDs and don't flow anywhere by themselves: any later run prompt
(or node prompt) uses one by mentioning its ID, e.g. "a video of
characters_2 dancing".

Names are the user's own text, sent and shown as written in every language.

A project runs on its collection's active workflow (``Project.workflow``).
In a project, each step is **run** with a prompt and a count: the prompt,
the project description, what earlier steps settled on and the nodes it
mentions go to a text model, which writes that many results (a text step)
or prompts (an image or video step, generated afterwards). Running a step
again replaces its nodes.

A step can also be **completed by hand** (``completeStep``): the user's own
texts, images or videos become its nodes, exactly as a run's results would
(nothing is generated or charged); its ``StepRun`` is then ``manual``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .common import (
    CompleteModel,
    ContractModel,
    Language,
    MaterialId,
    MediaKind,
    Timestamp,
)

# The most nodes one run of a step may make.
MAX_ITEMS = 20

MAX_STEP_DESCRIPTION = 4000

STEP_KEY = r"^[a-z][a-z0-9_]{0,39}$"


class Carry(StrEnum):
    """Which of a step's results go to later steps by themselves, as context
    (the decisions made so far); anything can still be used by mentioning
    it."""

    # All of them: a set that is used together (the cast, the script).
    all = "all"
    # None: only what a prompt mentions (@).
    none = "none"


class WorkflowStep(CompleteModel):
    # Stable identity (node IDs are "<key>_<n>"), set by the designer.
    key: str = Field(pattern=STEP_KEY)
    name: str = Field(min_length=1, max_length=80)
    # What this step is for, in the user's words: sent to the text model with
    # the project description whenever it writes for this step (a run, or a
    # AI edit of one of its nodes). Empty: nothing extra.
    description: str = Field(default="", max_length=MAX_STEP_DESCRIPTION)
    kind: MediaKind
    # How many a run makes unless the project says otherwise (the run form
    # starts with it). Null: no default, the project must say.
    count: int | None = Field(default=None, ge=1, le=MAX_ITEMS)
    # Which results later steps get by themselves (see Carry); not given:
    # "none".
    carry: Carry = Carry.none

    @model_validator(mode="before")
    @classmethod
    def _default_carry(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # Definitions saved by older clients may still carry an `output`;
        # such a step without a carry carried everything.
        old = "output" in data
        data = {k: v for k, v in data.items() if k != "output"}
        if data.get("carry") is None:
            return {**data, "carry": Carry.all if old else Carry.none}
        return data


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
    # Completed by hand (completeStep) rather than run; ``prompt`` is then
    # the last run's, kept for when the step is run again.
    manual: bool = False


class StepRunRequest(ContractModel):
    """``prompt`` is optional (the instructions, the step's description and
    earlier steps may be enough). ``count`` is required."""

    prompt: str = Field(default="", max_length=4000)
    count: int = Field(ge=1, le=MAX_ITEMS)


class StepEntry(ContractModel):
    """One result given by hand: ``text`` for a text step, or an uploaded
    file (``material_id``, from ``uploadMaterial``) for an image or video
    step. ``id`` names its node (cleaned and made unique, like a run's);
    blank: ``<step>_<n>``."""

    id: str | None = Field(default=None, max_length=80)
    text: str | None = Field(default=None, max_length=100_000)
    material_id: MaterialId | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> StepEntry:
        if (self.text is None) == (self.material_id is None):
            raise ValueError("give either text or material_id")
        return self


class StepCompleteRequest(ContractModel):
    """A step's results, in order."""

    entries: list[StepEntry] = Field(min_length=1, max_length=MAX_ITEMS)


# --- settings, approval, takes, AI edits ---------------------------------------------------


class AppSettings(CompleteModel):
    """App-wide settings, chosen on the landing page."""

    language: Language = Language.en


class AppSettingsUpdate(ContractModel):
    language: Language


class TakeCreate(ContractModel):
    """A text take written by hand (or applied from elsewhere)."""

    text: str = Field(min_length=1, max_length=100_000)


class EditTarget(StrEnum):
    #: The node's prompt (any generated node that has one, or none yet).
    prompt = "prompt"
    #: A workflow text node's result (its chosen take), or a text node's
    #: with no prompt.
    text = "text"


class AiEditRequest(ContractModel):
    """What to change, in the user's words ("a dog, not a cat")."""

    instruction: str = Field(min_length=1, max_length=4000)


class AiEdit(CompleteModel):
    """A suggested edit, not saved: ``text`` is the whole new prompt (or text
    result, see ``target``), changed only as asked. Apply it by saving the
    prompt (``updateNode``) or adding the text as a take (``addTake``)."""

    target: EditTarget
    text: str
    # A video's length after the edit (whole seconds); null for others.
    seconds: int | None = None
