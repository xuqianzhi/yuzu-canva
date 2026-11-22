"""Turn a node and its references into a job: which provider call, with what.

This is the routing table from contract/README.md. It only plans; the
worker runs the plan.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contract import (
    MAX_IMAGE_REFS,
    MAX_VIDEO_REFS,
    ErrorCode,
    JobInput,
    MediaKind,
    Node,
    Operation,
    Output,
    Provider,
    ResolvedRef,
)
from ..errors import ApiError
from .graph import MENTION
from .mentions import mentioned, replace_mentions
from .workflow import words


@dataclass(frozen=True)
class Reference:
    node: Node
    output: Output


@dataclass(frozen=True)
class Plan:
    provider: Provider
    operation: Operation
    job_input: JobInput


def _article(kind: MediaKind) -> str:
    return "an" if kind == MediaKind.image else "a"


def _route(kind: MediaKind, image_refs: int, video_refs: int) -> tuple[Provider, Operation]:
    if video_refs > MAX_VIDEO_REFS[kind]:
        if MAX_VIDEO_REFS[kind] == 0:
            raise ApiError(
                409,
                ErrorCode.unsupported_ref,
                f"{_article(kind)} {kind.value} node cannot use a video as an input; "
                "connect it to a video node instead",
            )
        raise ApiError(
            409,
            ErrorCode.too_many_refs,
            f"a {kind.value} node takes at most {MAX_VIDEO_REFS[kind]} video references",
        )
    if image_refs > MAX_IMAGE_REFS[kind]:
        raise ApiError(
            409,
            ErrorCode.too_many_refs,
            f"a {kind.value} node takes at most {MAX_IMAGE_REFS[kind]} image references",
        )
    if kind == MediaKind.text:
        return Provider.openai, Operation.text_generate
    if kind == MediaKind.image:
        op = Operation.image_edit if image_refs else Operation.image_generate
        return Provider.openai, op
    return Provider.seedance, Operation.video_generate


def _resolve_prompt(prompt: str, refs: list[Reference]) -> str:
    """Inline text references at their mentions. Image and video mentions are
    left as tokens; each provider rewrites them into its own labels."""
    texts = {r.node.id: r.output.text or "" for r in refs if r.output.kind == MediaKind.text}

    def replace(match):
        node_id = match.group(1)
        return texts.get(node_id, match.group(0))

    return MENTION.sub(replace, prompt).strip()


def plan(
    node: Node,
    refs: list[Reference],
    language: str = "en",
) -> Plan:
    """Validate a generate request and decide what to run.

    `refs` holds each referenced node with its selected output; callers raise
    `missing_ref_output` for references without one before calling this.
    `language` is the app's: the wording the backend adds is in it.
    """
    # Inputs go in the order the prompt first mentions their IDs, and each
    # mention becomes an internal token the providers turn into their labels
    # (image 1, 图片1...) or, for text, the text itself.
    ids = {r.node.name: r.node.id for r in refs if r.node.name}
    order = mentioned(node.prompt, ids)
    refs = sorted(
        refs, key=lambda r: order.index(r.node.id) if r.node.id in order else len(order)
    )
    node = node.model_copy(
        update={"prompt": replace_mentions(node.prompt, ids, lambda nid, _: f"@{{{nid}}}")}
    )

    image_refs = sum(r.output.kind == MediaKind.image for r in refs)
    video_refs = sum(r.output.kind == MediaKind.video for r in refs)
    provider, operation = _route(node.kind, image_refs, video_refs)

    prompt = _resolve_prompt(node.prompt, refs)
    if not prompt:
        raise ApiError(422, ErrorCode.validation_error, "the prompt is empty")

    return Plan(
        provider=provider,
        operation=operation,
        job_input=JobInput(
            prompt=prompt,
            params=node.params,
            refs=[
                ResolvedRef(node_id=r.node.id, output_id=r.output.id, kind=r.output.kind)
                for r in refs
            ],
            system=words(language)["plain"] if node.kind == MediaKind.text else "",
            language=language,
        ),
    )
