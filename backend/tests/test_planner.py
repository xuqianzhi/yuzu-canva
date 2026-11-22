"""Routing and prompt rules for generate, without HTTP."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from canvas_api.contract import MAX_IMAGE_REFS, MediaKind, Node, Operation, Output
from canvas_api.domain.graph import would_create_cycle
from canvas_api.domain.planner import Reference, _route, plan
from canvas_api.errors import ApiError

NOW = datetime(2026, 11, 18, tzinfo=UTC)


def node(node_id: str, kind: str = "image", prompt: str = "x") -> Node:
    return Node(
        id=node_id,
        project_id="prj_1",
        kind=kind,
        position={"x": 0, "y": 0},
        prompt=prompt,
        params={"kind": kind},
        created_at=NOW,
        updated_at=NOW,
    )


def ref(node_id: str, kind: str, text: str | None = None) -> Reference:
    output = Output(
        id=f"out_{node_id[4:]}",
        node_id=node_id,
        job_id="job_1",
        kind=kind,
        text=text,
        created_at=NOW,
    )
    return Reference(node=node(node_id, kind), output=output)


@pytest.mark.parametrize(
    ("kind", "images", "videos", "operation"),
    [
        ("text", 0, 0, Operation.text_generate),
        ("text", 2, 0, Operation.text_generate),
        ("image", 0, 0, Operation.image_generate),
        ("image", 1, 0, Operation.image_edit),
        ("video", 0, 0, Operation.video_generate),
        ("video", 9, 3, Operation.video_generate),
    ],
)
def test_routing(kind, images, videos, operation):
    assert _route(MediaKind(kind), images, videos)[1] == operation


@pytest.mark.parametrize(
    ("kind", "images", "videos", "code"),
    [
        ("image", 0, 1, "unsupported_ref"),
        ("text", 0, 1, "unsupported_ref"),
        ("video", 0, 4, "too_many_refs"),
        ("video", 10, 0, "too_many_refs"),
        ("image", MAX_IMAGE_REFS[MediaKind.image] + 1, 0, "too_many_refs"),
    ],
)
def test_routing_errors(kind, images, videos, code):
    with pytest.raises(ApiError) as caught:
        _route(MediaKind(kind), images, videos)
    assert caught.value.detail.code == code


def test_text_references_are_inlined_at_their_mentions():
    target = node("nod_t", "image", "a cat, @{nod_s}, at night")
    planned = plan(target, [ref("nod_s", "text", text="wearing a hat")])
    assert planned.operation == Operation.image_generate
    assert planned.job_input.prompt == "a cat, wearing a hat, at night"
    assert planned.job_input.refs[0].output_id == "out_s"


def test_cycle_detection():
    from canvas_api.contract import Edge

    def edge(s, t):
        return Edge(
            id=f"edg_{s}{t}",
            project_id="prj_1",
            source_node_id=f"nod_{s}",
            target_node_id=f"nod_{t}",
            created_at=NOW,
        )

    edges = [edge("a", "b"), edge("b", "c")]
    assert would_create_cycle(edges, "nod_c", "nod_a")
    assert not would_create_cycle(edges, "nod_a", "nod_c")
