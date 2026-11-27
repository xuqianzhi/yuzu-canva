"""The workflow engine's pure parts: the built-in template, what the model
is told when a step runs (and in an AI edit of a node), and layout.

Steps are data (contract/workflow.py): a name and a node kind. Their names
are the user's text and are never translated.

What the model is told is one set of English wording (``W``), whatever the
app's language: the user's own words (project description, step
description, mentioned nodes, request) go inside tags, and the model
is told to write in the language of those words. So a Chinese request gets
Chinese results and IDs even with the app in English, and any language
works, not just the app's two.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any

from ..contract import (
    Carry,
    MediaKind,
    Node,
    Output,
    Project,
    WorkflowDefinition,
    WorkflowStep,
)
from .mentions import mentioned

# --- the built-in template --------------------------------------------------------

BUILTIN_ID = "wft_builtin"


def builtin_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        id=BUILTIN_ID,
        version=1,
        name="Default",
        steps=[
            WorkflowStep(
                key="characters",
                name="Character",
                kind=MediaKind.image,
                carry=Carry.all,
                description=(
                    "Design the recurring characters of this video, one image per "
                    "character: full body, facing the camera, on a plain background, so "
                    "later steps can use them by ID (characters_1, characters_2...). Give "
                    "each a distinctive, easy-to-repeat look (face, hair, clothes, "
                    "colours), all in one shared art style."
                ),
            ),
            WorkflowStep(
                key="dishes",
                name="Dish brainstorming",
                kind=MediaKind.text,
                description=(
                    "Brainstorm dishes the video could feature. For each: its name, one "
                    "sentence on what it is, and what makes it look good on camera. Keep "
                    "them varied in cuisine, colour and difficulty."
                ),
                # A brainstorm: later steps get a dish only by mentioning it.
                carry=Carry.none,
            ),
            WorkflowStep(
                key="dish_images",
                name="Dish image",
                kind=MediaKind.image,
                carry=Carry.all,
                description=(
                    "One appetising image per dish: the finished dish, plated and "
                    "styled, in the same art style as the characters, so it can appear "
                    "in the video."
                ),
            ),
            WorkflowStep(
                key="script",
                name="Script overview",
                kind=MediaKind.text,
                carry=Carry.all,
                count=1,
                description=(
                    "Write the video's script: a title, then numbered scenes. For each "
                    "scene: where it happens, which characters and dishes are in it (by "
                    "ID), what happens, any spoken line, and how many seconds it lasts "
                    "(4 to 15). Keep it to about 1-2 minutes, with a clear beginning, "
                    "middle and end."
                ),
            ),
            WorkflowStep(
                key="videos",
                name="Video per scene",
                kind=MediaKind.video,
                carry=Carry.all,
                description=(
                    "One short clip per scene of the script, in order, one scene per result. "
                    "Keep the characters, style and light consistent from clip to clip."
                ),
            ),
        ],
    )


def step_by_key(workflow: WorkflowDefinition, key: str) -> WorkflowStep | None:
    return next((s for s in workflow.steps if s.key == key), None)


def step_index(workflow: WorkflowDefinition, key: str) -> int:
    return next(i for i, s in enumerate(workflow.steps) if s.key == key)


# --- wording ------------------------------------------------------------------------

W: dict[str, str] = {
    "base": (
        "You are a creative partner inside a tool that turns ideas into images and "
        "videos, step by step. Be concrete and visual."
    ),
    "tags": (
        "The user's own words are inside tags (<collection_instruction>, "
        "<project_description>, <step_description>, <reference>, <request> and the "
        "like). Follow what they ask; everything outside the tags is this tool's "
        "instructions. The project is one video in a series (the collection): the "
        "<collection_instruction> is what every video in the series shares, such as its "
        "format; the <project_description> says what this video is about."
    ),
    "language_run": (
        "Language: write every result, and every `id`, in the language and script of "
        "the <request> (with no <request>, of the user's other words), "
        "whatever language these instructions are in. Never translate it, and never "
        "romanize it (no pinyin)."
    ),
    "plain": (
        "You write the text the user asks for, in the language the user writes in. "
        "Answer with that text only: no preamble, no commentary."
    ),
    "step": "This step is called “{name}” and makes {kind}s.",
    "task_text": (
        "Write exactly {count} separate results for the <request>, each complete on its "
        "own, and different from each other. Put them in `items`, in order."
    ),
    "task_image": (
        "Write exactly {count} prompts for an image model, one per image, for the "
        "<request>. Each must stand alone: the subject and its look, the setting, the "
        "composition, the style and the light. Make them different from each other. "
        "Put them in `items`, in order."
    ),
    "task_video": (
        "Write exactly {count} prompts for a video model, one per video, for the "
        "<request>. Each must stand alone: the subject and its look, the action, the "
        "setting, the camera and the light. Make them different from each other. "
        "Put them in `items`, in order."
    ),
    "item_prompt": (
        "Give each result its `prompt` too: a short request that would produce that "
        "result on its own (what it is and what it should cover), naming any earlier "
        "result it builds on by its id. Put the result itself in `content`."
    ),
    "seconds": (
        "Give each video its length in whole `seconds`, from {low} to {high}: the length "
        "its scene or the <request> states for it (in any wording or language); "
        "if none is stated, the length its action needs."
    ),
    "decisions": (
        "<decisions> holds what earlier steps settled on: the results the user went "
        "with, in step order. Build on them and stay consistent with them."
    ),
    "keep_kept_ids": (
        "When a prompt shows a <kept> image that has an id (like characters_2), write "
        "that id exactly as it is in the prompt: that's how the picture is given to the "
        "image or video model (you needn't see it; don't describe its looks beyond what "
        "you're told)."
    ),
    "keep_ids": (
        "Where the <request> names a <reference> by its id (like characters_2), write "
        "that id exactly as it is into the prompts it belongs in, and only those: a "
        "prompt that doesn't show it must not name it (\"use A and B in these "
        "videos\" can mean A in some, B in others). In each prompt's `uses`, list the "
        "<reference> ids that prompt names (empty if none)."
    ),
    "name_items": (
        "Give each result an `id`: a short name for what it is, like a character's or a "
        "dish's name, 2 to 12 characters, in the language and script of the <request>. "
        "Letters of any script are fine (Chinese characters too, e.g. 怪人), as are "
        "digits, _ and -; no spaces. Each `id` must differ from the others and from the "
        "IDs already in the project ({taken}). Don't write one result's `id` in another "
        "result's `content`."
    ),
    "no_request": (
        "There's no <request> this time: work from the instructions, this step's "
        "description and the <decisions>."
    ),
    "none": "none",
    "an_image": "(an image, attached as {label})",
    "named_image": (
        "(an image, attached as {label}. In what you write, call it {name}, never {label}.)"
    ),
    "a_video": "(a video)",
    "made_from": "(a generated {kind}, not attached; made from this prompt:)\n{prompt}",
    "provided": "({kind} the user provided, not attached)",
    "edit_task": (
        "Edit the <current> {what} as the <change> asks, and only that: make the smallest "
        "edit that does it and keep everything else exactly as it is, word for word -- "
        "the wording, the style and the details. Keep every id (like characters_2) "
        "exactly as written: that's how the user's references reach the model. Don't "
        "add, drop or improve anything the <change> doesn't ask for. Put the whole new "
        "{what} in `content`."
    ),
    "edit_seconds": (
        "Give the video's length in whole `seconds`, from {low} to {high}: {current}, "
        "unless the <change> asks for another length."
    ),
    "language_edit": (
        "Language: write in the language and script of the <current> {what}, unless the "
        "<change> asks for another. Never translate or romanize it otherwise."
    ),
    "what_prompt": "prompt for a {kind} model",
    "what_text": "text",
}

# Chinese characters (and the kana used with them).
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def image_label(n: int, text: str = "") -> str:
    """How a prompt names its n-th attached image: in the script of the
    prompt it goes into ("图片1" in Chinese text, else "image 1")."""
    return f"图片{n}" if _CJK.search(text) else f"image {n}"


def _tag(name: str, text: str, **attrs: str) -> str:
    """The user's words in a tag (<name attr="...">text</name>)."""
    head = "".join(f' {k}="{v}"' for k, v in attrs.items())
    return f"<{name}{head}>\n{text.strip()}\n</{name}>"


# --- answer shapes ---------------------------------------------------------------------

_STRING = {"type": "string"}


@dataclass(frozen=True)
class OutputSpec:
    """The shape a model's answer must have: a name and a JSON schema, or
    None for plain text."""

    name: str
    schema: dict[str, Any] | None


# A video's length, as Seedance takes it.
MIN_SECONDS = 4
MAX_SECONDS = 15


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    """A JSON schema for an object with exactly these (all required) fields."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def _item(named: bool, seconds: bool, prompted: bool, uses: bool) -> dict[str, Any]:
    if not named and not seconds and not prompted and not uses:
        return _STRING
    properties: dict[str, Any] = {"id": _STRING} if named else {}
    if prompted:
        properties["prompt"] = _STRING
    properties["content"] = _STRING
    if seconds:
        properties["seconds"] = {"type": "integer"}
    if uses:
        properties["uses"] = {"type": "array", "items": _STRING}
    return _object(properties)


def run_spec(
    count: int,
    named: bool = False,
    seconds: bool = False,
    prompted: bool = False,
    uses: bool = False,
) -> OutputSpec:
    """A run's answer: exactly `count` results (or prompts); `named`, each
    with an `id` to name its node; `seconds`, each (a video) with its
    length; `prompted`, each (a text result) with the prompt that would
    make it; `uses`, each (an image or video prompt) with the mentioned
    references it names."""
    items = {
        "type": "array",
        "minItems": count,
        "maxItems": count,
        "items": _item(named, seconds, prompted, uses),
    }
    return OutputSpec(name="run", schema=_object({"items": items}))


@dataclass(frozen=True)
class RunItem:
    """One result of a run: its text (a text node's take, or an image or
    video node's prompt) and the ID the model gave it, if any."""

    text: str
    name: str | None = None
    # A video's length (whole seconds, MIN_SECONDS to MAX_SECONDS).
    seconds: int | None = None
    # A text result's prompt: a request that would make it on its own.
    prompt: str | None = None
    # The mentioned references an image or video prompt names, as the model
    # listed them (see keep_used).
    uses: tuple[str, ...] = ()


def clamp_seconds(value: object) -> int | None:
    """A length the model gave, as whole seconds Seedance takes; None if it
    isn't a number."""
    if isinstance(value, bool):
        return None
    try:
        seconds = round(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return max(MIN_SECONDS, min(MAX_SECONDS, seconds))


class RunFormatError(ValueError):
    """A run answer that isn't a list of results."""


def parse_run(answer: str, count: int) -> list[RunItem]:
    """The results of a run answer, plain or named: blanks dropped, at most
    `count`."""
    try:
        raw = json.loads(answer)["items"]
        if not isinstance(raw, list):
            raise TypeError
    except (ValueError, KeyError, TypeError) as exc:
        raise RunFormatError("the answer is not a list of results") from exc
    items = []
    for entry in raw:
        seconds = prompt = None
        uses: tuple[str, ...] = ()
        if isinstance(entry, dict):
            text, name = str(entry.get("content") or "").strip(), entry.get("id")
            name = str(name).strip() if name is not None else None
            seconds = clamp_seconds(entry.get("seconds"))
            prompt = str(entry.get("prompt") or "").strip() or None
            listed = entry.get("uses")
            if isinstance(listed, list):
                uses = tuple(str(u).strip() for u in listed if str(u).strip())
        else:
            text, name = str(entry).strip(), None
        if text:
            items.append(RunItem(text, name or None, seconds, prompt, uses))
    return items[:count]


def keep_used(item: RunItem, ids: list[str]) -> RunItem:
    """An image or video prompt with each mentioned ID it uses written in:
    the ones the model listed in `uses` but left out of the text are added
    (an ID in the prompt is what gives its node that reference). `ids` are
    the request's mentions: one the model doesn't list stays out, and `uses`
    can't add any other."""
    by_key = {i.casefold(): i for i in ids}
    listed = [by_key[u.casefold()] for u in item.uses if u.casefold() in by_key]
    # Written already, by the rules for mentions ("fox" isn't in "fox_2").
    written = set(mentioned(item.text, {i: i for i in ids}))
    missing = [i for i in dict.fromkeys(listed) if i not in written]
    return replace(item, text=" ".join([item.text, *missing]))


# --- layout ---------------------------------------------------------------------------

# Steps run left to right, right of the global assets column; a step's nodes
# are a column, one per row.
LAYOUT_X = 680.0
LAYOUT_Y = 60.0
LAYOUT_DX = 560.0
LAYOUT_DY = 600.0


def position_for(workflow: WorkflowDefinition, key: str, index: int) -> tuple[float, float]:
    return LAYOUT_X + step_index(workflow, key) * LAYOUT_DX, LAYOUT_Y + index * LAYOUT_DY


# --- what the model is told -----------------------------------------------------------


@dataclass(frozen=True)
class Piece:
    """A node's output given to a run: its text, or (for an image sent with
    the request) the label it is sent as, e.g. "image 1"."""

    kind: str
    text: str | None = None
    label: str | None = None
    # The node's ID, for a mentioned (or carried-forward) node.
    name: str | None = None
    # The step that made it, for a carried-forward node.
    step: str | None = None


@dataclass(frozen=True)
class Instructions:
    """The standing guidance for a project's runs and AI edits: its collection's
    (shared by the series) and its own (this video)."""

    collection: str = ""
    project: str = ""

    @classmethod
    def of(cls, project: Project) -> Instructions:
        return cls(project.collection_instruction, project.description)

    def tagged(self) -> list[str]:
        parts = []
        if self.collection.strip():
            parts.append(_tag("collection_instruction", self.collection))
        if self.project.strip():
            parts.append(_tag("project_description", self.project))
        return parts


def _body(piece: Piece) -> str:
    if piece.text is not None:
        return piece.text
    if piece.kind == "image":
        if piece.name:
            return W["named_image"].format(label=piece.label or "", name=piece.name)
        return W["an_image"].format(label=piece.label or "")
    return W["a_video"]


def run_messages(
    step: WorkflowStep,
    prompt: str,
    count: int,
    instructions: Instructions,
    references: list[Piece],
    naming: Naming | None = None,
    decisions: list[Piece] | None = None,
) -> tuple[str, str]:
    """(system, user) for running a step. `references` are the nodes the
    prompt mentions; `naming`, when results are to be named (see run_spec); `decisions`, what
    earlier steps settled on (Store.carried_forward). The user's words are
    tagged; the rest is W's English."""
    parts = [W["base"], W["tags"], W["language_run"], *instructions.tagged()]
    if decisions:
        parts.append(W["decisions"])
    task = W[f"task_{step.kind.value}"].format(count=count)
    if step.kind != MediaKind.text:
        if references:
            task += " " + W["keep_ids"]
        if any(d.kind == "image" and d.name for d in decisions or []):
            task += " " + W["keep_kept_ids"]
    if step.kind == MediaKind.text:
        task += " " + W["item_prompt"]
    if step.kind == MediaKind.video:
        task += " " + W["seconds"].format(low=MIN_SECONDS, high=MAX_SECONDS)
    if naming is not None:
        task += " " + W["name_items"].format(taken=_id_list(naming.taken))
    if not prompt.strip():
        task += " " + W["no_request"]
    parts.append(_step_block(step, task))
    system = "\n\n".join(parts)

    user = [decisions_block(decisions)] if decisions else []
    user += [_tag("reference", _body(r), id=r.name or "") for r in references]
    if prompt.strip():
        user.append(_tag("request", prompt))
    return system, "\n\n".join(user)


def carried_piece(step: str, node: Node, output: Output) -> Piece:
    """A result an earlier step settled on, as text: a text result whole; an
    image or video (never attached: costly) as the prompt that made it, or
    as provided by the user (uploaded, or a step completed by hand)."""
    kind = output.kind.value
    if output.kind == MediaKind.text:
        text = output.text or ""
    elif node.prompt.strip():
        text = W["made_from"].format(kind=kind, prompt=node.prompt.strip())
    else:
        text = W["provided"].format(kind="an image" if kind == "image" else f"a {kind}")
    return Piece(kind=kind, text=text, name=node.name, step=step)


def decisions_block(decisions: list[Piece]) -> str:
    """What earlier steps settled on, tagged: <kept step=... id=... kind=...>."""
    kept = []
    for piece in decisions:
        attrs = {"step": piece.step or ""}
        if piece.name:
            attrs["id"] = piece.name
        if piece.kind != "text":
            attrs["kind"] = piece.kind
        kept.append(_tag("kept", _body(piece), **attrs))
    return "<decisions>\n" + "\n".join(kept) + "\n</decisions>"


@dataclass(frozen=True)
class Naming:
    """What the model needs to name a run's results: the project's other
    IDs (not the step's own: a run names its results afresh)."""

    taken: list[str]


# At most this many existing IDs are listed for the model.
_MAX_LISTED_IDS = 80


def _id_list(ids: list[str]) -> str:
    return ", ".join(ids[:_MAX_LISTED_IDS]) if ids else W["none"]


def name_images(items: list[str], references: list[Piece]) -> list[str]:
    """Put back each mentioned image's ID where the model wrote the label it
    was sent as ("image 1", "图片1") instead. The numbers only hold for the
    call that wrote them: each generation numbers its own references, from
    the IDs."""
    names: dict[int, str] = {}
    for piece in references:
        number = re.search(r"\d+", piece.label or "")
        if piece.name and number:
            names[int(number.group())] = piece.name
    if not names:
        return items
    label = re.compile(r"(?<![A-Za-z0-9_])(?:[Ii]mage|图片)\s*(\d+)(?!\d)")

    def replace(match: re.Match[str]) -> str:
        return names.get(int(match.group(1)), match.group(0))

    return [label.sub(replace, item) for item in items]


def _step_block(step: WorkflowStep, task: str) -> str:
    """The step's name and kind, its description (the user's words), and
    what to do now."""
    lines = [W["step"].format(name=step.name, kind=step.kind.value)]
    if step.description.strip():
        lines.append(_tag("step_description", step.description))
    lines.append(task)
    return "\n".join(lines)


def edit_spec(seconds: bool) -> OutputSpec:
    """An edit's answer: the whole new text, and for a video its length."""
    properties: dict[str, Any] = {"content": _STRING}
    if seconds:
        properties["seconds"] = {"type": "integer"}
    return OutputSpec(name="edit", schema=_object(properties))


def edit_messages(
    instructions: Instructions,
    step: WorkflowStep | None,
    what: str,
    current: str,
    change: str,
    references: list[Piece],
    decisions: list[Piece],
    seconds: int | None = None,
) -> tuple[str, str]:
    """(system, user) for editing one node's prompt (or text result) as the
    user asks. `what` names it ("prompt for a video model", "text");
    `references`, the nodes it mentions; `decisions`, what earlier steps
    settled on; `seconds`, a video's current length."""
    task = W["edit_task"].format(what=what)
    if seconds is not None:
        task += " " + W["edit_seconds"].format(
            low=MIN_SECONDS, high=MAX_SECONDS, current=seconds
        )
    parts = [W["base"], W["tags"], W["language_edit"].format(what=what)]
    parts += instructions.tagged()
    if decisions:
        parts.append(W["decisions"])
    parts.append(_step_block(step, task) if step is not None else task)
    user = [decisions_block(decisions)] if decisions else []
    user += [_tag("reference", _body(r), id=r.name or "") for r in references]
    user += [_tag("current", current), _tag("change", change)]
    return "\n\n".join(parts), "\n\n".join(user)


def parse_edit(answer: str) -> tuple[str, int | None]:
    """The new text and (a video's) length from an edit's answer. Raises
    RunFormatError if there's no text."""
    try:
        data = json.loads(answer)
    except json.JSONDecodeError:
        data = {"content": answer}
    text = str(data.get("content") or "").strip() if isinstance(data, dict) else ""
    if not text:
        raise RunFormatError("the model returned no text")
    return text, clamp_seconds(data.get("seconds"))
