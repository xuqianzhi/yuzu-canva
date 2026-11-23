"""The contract's own validation rules."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from canvas_api.contract import (
    EdgeCreate,
    ImageParams,
    MediaKind,
    Node,
    NodeCreate,
    NodeUpdate,
    VideoParams,
    default_params,
)

NOW = datetime(2026, 11, 18, tzinfo=UTC)


def test_node_create_defaults_params_to_none_and_accepts_matching_params():
    assert NodeCreate(kind="image", position={"x": 0, "y": 0}).params is None
    node = NodeCreate(kind="video", position={"x": 0, "y": 0}, params={"kind": "video"})
    assert isinstance(node.params, VideoParams)
    assert node.params.duration_s == 4


def test_params_must_match_node_kind():
    with pytest.raises(ValidationError, match="does not match node kind"):
        NodeCreate(kind="image", position={"x": 0, "y": 0}, params={"kind": "video"})
    with pytest.raises(ValidationError, match="does not match node kind"):
        NodeUpdate(kind="text", params={"kind": "image"})


def test_params_are_discriminated_by_kind():
    update = NodeUpdate(params={"kind": "image", "size": "1536x1024"})
    assert isinstance(update.params, ImageParams)
    with pytest.raises(ValidationError):
        NodeUpdate(params={"kind": "image", "duration_s": 5})  # video-only field


@pytest.mark.parametrize("duration", [3, 16])
def test_video_duration_bounds(duration):
    with pytest.raises(ValidationError):
        VideoParams(duration_s=duration)


def test_default_params_per_kind():
    for kind in MediaKind:
        assert default_params(kind).kind == kind


def test_ids_are_prefixed():
    EdgeCreate(source_node_id="nod_a", target_node_id="nod_b")
    with pytest.raises(ValidationError):
        EdgeCreate(source_node_id="prj_a", target_node_id="nod_b")


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        NodeUpdate(promt="typo")


def test_node_round_trips_through_json():
    node = Node(
        id="nod_1",
        project_id="prj_1",
        kind="image",
        position={"x": 1, "y": 2},
        prompt="a fox, style of @{nod_0}",
        params={"kind": "image"},
        created_at=NOW,
        updated_at=NOW,
    )
    assert Node.model_validate_json(node.model_dump_json()) == node
