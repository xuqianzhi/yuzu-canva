"""The workflow engine's pure parts: the built-in template, what the model
is told when a step runs (and in a node's chat), and layout.

Steps are data (contract/workflow.py): a name and a node kind. Their names
are the user's text and are never translated; only the backend's own
wording around them (``WORDS``) follows the app's language.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..contract import Language, MediaKind, OutputUse, WorkflowDefinition, WorkflowStep

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
            ),
            WorkflowStep(
                key="dish_images",
                name="Dish image",
                kind=MediaKind.image,
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
                count=1,
                description=(
                    "Write the video's script: a title, then numbered scenes. For each "
                    "scene: where it happens, which characters and dishes are in it (by "
                    "ID), what happens, and any spoken line. Keep it to about 1-2 "
                    "minutes, with a clear beginning, middle and end."
                ),
            ),
            WorkflowStep(
                key="scene_prompts",
                name="Prompt per scene",
                kind=MediaKind.text,
                output=OutputUse.one_to_one,
                description=(
                    "Turn each scene of the script into the prompt for its video clip, "
                    "in order, one scene per result. Each result is sent to the video "
                    "model exactly as written, so it is the prompt itself and nothing "
                    "else: no title, scene number, notes or explanation."
                ),
            ),
            WorkflowStep(
                key="videos",
                name="Video per prompt",
                kind=MediaKind.video,
                description=(
                    "One short clip per scene prompt from the step before. Keep the "
                    "characters, style and light consistent from clip to clip."
                ),
            ),
        ],
    )


def step_by_key(workflow: WorkflowDefinition, key: str) -> WorkflowStep | None:
    return next((s for s in workflow.steps if s.key == key), None)


def step_index(workflow: WorkflowDefinition, key: str) -> int:
    return next(i for i, s in enumerate(workflow.steps) if s.key == key)


# --- wording ------------------------------------------------------------------------

WORDS: dict[str, dict[str, str]] = {
    "en": {
        "base": (
            "You are a creative partner inside a tool that turns ideas into images and "
            "videos, step by step. Answer in the language the user writes in. Be "
            "concrete and visual."
        ),
        "plain": (
            "You write the text the user asks for. Answer with that text only: no "
            "preamble, no commentary."
        ),
        "instruction": "## Project instruction",
        "step": "## This step: {name}",
        "task_text": (
            "Write exactly {count} separate results for the request, each complete on its "
            "own, and different from each other. Put them in `items`, in order."
        ),
        "task_image": (
            "Write exactly {count} prompts for an image model, one per image, for the "
            "request. Each must stand alone: the subject and its look, the setting, the "
            "composition, the style and the light. Make them different from each other. "
            "Put them in `items`, in order."
        ),
        "task_video": (
            "Write exactly {count} prompts for a video model, one per video, for the "
            "request. Each must stand alone: the subject and its look, the action, the "
            "setting, the camera and the light. Make them different from each other. "
            "Put them in `items`, in order."
        ),
        "task_each": (
            "Write one result for each of the {count} inputs, in the same order (result 1 "
            "for input 1, and so on), following the request. Put them in `items`."
        ),
        "keep_ids": (
            "Where the request names node IDs (like characters_2), write those IDs exactly "
            "as they are into the prompts they belong in."
        ),
        "referenced": "## {name}",
        "inputs": "## Inputs, one per result",
        "input": "Input {n}",
        "an_image": "(an image, sent as {label})",
        "a_video": "(a video)",
        "request": "## Request",
        "how": (
            "## How to answer\nYou are helping the user improve this text. Put a short "
            "answer in `reply`. When the user asks for changes, or you suggest an improved "
            "version, put the complete new version in `proposal` (never a diff); otherwise "
            "set `proposal` to null."
        ),
        "current": "## Current version",
        "none_yet": "(none yet)",
        "context_note": "(This is the context of our conversation.)",
        "understood": "Understood.",
        "image": "image {n}",
    },
    "zh": {
        "base": (
            "你是一个创作搭档，所在的工具会把想法一步步变成图片和视频。请用中文写作，"
            "除非用户明确要求其他语言。要具体、有画面感。"
        ),
        "plain": "按用户的要求写出文字。只输出这段文字：不要开场白，也不要评论。",
        "instruction": "## 项目指令",
        "step": "## 这一步：{name}",
        "task_text": (
            "针对下面的要求，写出正好 {count} 个彼此不同、各自完整的结果。按顺序放进 `items`。"
        ),
        "task_image": (
            "针对下面的要求，为图片模型写出正好 {count} 条提示词，每张图片一条。"
            "每条都要能独立成立：主体及其外观、场景、构图、风格和光线。彼此要有区别。"
            "按顺序放进 `items`。"
        ),
        "task_video": (
            "针对下面的要求，为视频模型写出正好 {count} 条提示词，每个视频一条。"
            "每条都要能独立成立：主体及其外观、动作、场景、镜头和光线。彼此要有区别。"
            "按顺序放进 `items`。"
        ),
        "task_each": (
            "按照要求，为下面 {count} 个输入各写一个结果，"
            "顺序一致（结果 1 对应输入 1，依此类推）。放进 `items`。"
        ),
        "keep_ids": (
            "要求中提到节点 ID（例如 characters_2）的地方，请在相应的提示词里原样写出这些 ID。"
        ),
        "referenced": "## {name}",
        "inputs": "## 输入（每个结果对应一个）",
        "input": "输入 {n}",
        "an_image": "（一张图片，作为{label}发送）",
        "a_video": "（一个视频）",
        "request": "## 要求",
        "how": (
            "## 如何回答\n你在帮助用户改进这段文字。在 `reply` 中简短回答。当用户要求修改，"
            "或你提出改进版本时，把完整的新版本放进 `proposal`（不要只写差异）；"
            "否则把 `proposal` 设为 null。"
        ),
        "current": "## 当前版本",
        "none_yet": "（暂无）",
        "context_note": "（以上是我们这次对话的背景。）",
        "understood": "明白。",
        "image": "图片{n}",
    },
}


def words(language: str) -> dict[str, str]:
    return WORDS.get(language, WORDS[Language.en.value])


def image_label(language: str, n: int) -> str:
    """How an OpenAI prompt names its n-th reference image."""
    return words(language)["image"].format(n=n)


# --- answer shapes ---------------------------------------------------------------------

_STRING = {"type": "string"}


@dataclass(frozen=True)
class OutputSpec:
    """The shape a model's answer must have: a name and a JSON schema, or
    None for plain text."""

    name: str
    schema: dict[str, Any] | None


def chat_spec() -> OutputSpec:
    """A chat answer: a reply, and optionally a complete new version."""
    return OutputSpec(
        name="chat",
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["reply", "proposal"],
            "properties": {
                "reply": _STRING,
                "proposal": {"anyOf": [_STRING, {"type": "null"}]},
            },
        },
    )


def run_spec(count: int) -> OutputSpec:
    """A run's answer: exactly `count` results (or prompts)."""
    return OutputSpec(
        name="run",
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": _STRING,
                }
            },
        },
    )


class RunFormatError(ValueError):
    """A run answer that isn't a list of results."""


def parse_run(answer: str, count: int) -> list[str]:
    """The results of a run answer: blanks dropped, at most `count`."""
    try:
        raw = json.loads(answer)["items"]
        if not isinstance(raw, list):
            raise TypeError
    except (ValueError, KeyError, TypeError) as exc:
        raise RunFormatError("the answer is not a list of results") from exc
    items = [str(item).strip() for item in raw if str(item).strip()]
    return items[:count]


# --- layout ---------------------------------------------------------------------------

# Steps run left to right, right of the global assets column; a step's nodes
# are a column, one per row.
LAYOUT_X = 560.0
LAYOUT_Y = 60.0
LAYOUT_DX = 400.0
LAYOUT_DY = 500.0


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
    # The node's ID, for a mentioned node.
    name: str | None = None


def _body(piece: Piece, w: dict[str, str]) -> str:
    if piece.text is not None:
        return piece.text
    if piece.kind == "image":
        return w["an_image"].format(label=piece.label or "")
    return w["a_video"]


def run_messages(
    step: WorkflowStep,
    prompt: str,
    count: int,
    instruction: str,
    references: list[Piece],
    inputs: list[Piece] | None,
    language: str,
) -> tuple[str, str]:
    """(system, user) for running a step. `references` are the nodes the
    prompt mentions; `inputs` the one-to-one inputs (one per result)."""
    w = words(language)
    parts = [w["base"]]
    if instruction.strip():
        parts.append(f"{w['instruction']}\n{instruction.strip()}")
    if inputs is not None:
        task = w["task_each"].format(count=count)
    else:
        task = w[f"task_{step.kind.value}"].format(count=count)
        if step.kind != MediaKind.text and references:
            task += " " + w["keep_ids"]
    parts.append(_step_block(step, w, task))
    system = "\n\n".join(parts)

    user = [f"{w['referenced'].format(name=r.name)}\n{_body(r, w)}" for r in references]
    if inputs is not None:
        lines = [w["inputs"]]
        for n, piece in enumerate(inputs, start=1):
            lines.append(f"{w['input'].format(n=n)}: {_body(piece, w)}")
        user.append("\n".join(lines))
    if prompt.strip():
        user.append(f"{w['request']}\n{prompt.strip()}")
    return system, "\n\n".join(user)


def _step_block(step: WorkflowStep, w: dict[str, str], task: str | None = None) -> str:
    """ "## This step: <name>", its description (the user's own words), and
    what to do now, if given."""
    lines = [w["step"].format(name=step.name)]
    if step.description.strip():
        lines.append(step.description.strip())
    if task:
        lines.append(task)
    return "\n".join(lines)


def chat_system(instruction: str, step: WorkflowStep | None, language: str) -> str:
    w = words(language)
    parts = [w["base"]]
    if instruction.strip():
        parts.append(f"{w['instruction']}\n{instruction.strip()}")
    if step is not None:
        parts.append(_step_block(step, w))
    parts.append(w["how"])
    return "\n\n".join(parts)


def current_version_block(current: str | None, language: str) -> str:
    w = words(language)
    return f"{w['current']}\n{current if current is not None else w['none_yet']}"
