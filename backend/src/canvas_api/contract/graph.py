"""Nodes and edges: the canvas document.

A node takes a prompt and generates one kind of media (text, image or video).
An edge source -> target means "target references source": when the target
is generated, the source's selected output is used as an input.

Prompt mentions
---------------
A prompt refers to another node by containing its ID (its ``name``), e.g.
``"the fox from fox_1 running through snow"``; links exist exactly when a
prompt mentions their source (see contract/README.md). When generating, a
text input's mention is replaced by its text, and an image or video
mention by whatever the provider calls it ("image 1", "图片1"...).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    CompleteModel,
    ContractModel,
    EdgeId,
    MediaKind,
    NodeId,
    NodeSource,
    OutputId,
    Position,
    ProjectId,
    Size,
    Timestamp,
)

NAME_MAX = 80


def normalize_name(name: str | None) -> str | None:
    """Trim and collapse whitespace; blank means "no name"."""
    if name is None:
        return None
    cleaned = " ".join(name.split())
    return cleaned or None


def name_key(name: str) -> str:
    """What uniqueness compares: case- and spacing-insensitive."""
    return " ".join(name.split()).casefold()


# --- Per-kind generation settings --------------------------------------------


class TextParams(CompleteModel):
    kind: Literal["text"] = "text"


class ImageParams(CompleteModel):
    kind: Literal["image"] = "image"
    size: Literal["auto", "1024x1024", "1536x1024", "1024x1536"] = "auto"
    quality: Literal["auto", "low", "medium", "high"] = "auto"


class VideoParams(CompleteModel):
    kind: Literal["video"] = "video"
    resolution: Literal["480p", "720p", "1080p"] = "480p"
    ratio: Literal["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"] = "9:16"
    duration_s: int = Field(default=4, ge=4, le=15)
    generate_audio: bool = True
    # Null lets Seedance pick one.
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


NodeParams = Annotated[TextParams | ImageParams | VideoParams, Field(discriminator="kind")]


def default_params(kind: MediaKind) -> TextParams | ImageParams | VideoParams:
    return {
        MediaKind.text: TextParams,
        MediaKind.image: ImageParams,
        MediaKind.video: VideoParams,
    }[kind]()


def _check_params_kind(kind: MediaKind | None, params: object) -> None:
    if kind is not None and params is not None and params.kind != kind:  # type: ignore[attr-defined]
        raise ValueError(f"params.kind {params.kind!r} does not match node kind {kind.value!r}")  # type: ignore[attr-defined]


# --- Nodes ---------------------------------------------------------------------


class Node(CompleteModel):
    id: NodeId
    project_id: ProjectId
    kind: MediaKind
    # The node's ID, shown as "ID" in the UI (``id`` is the internal key):
    # optional, unique in the project ignoring case, letters (any script),
    # digits, "_" and "-". A node needs one for anything to refer to it, and
    # prompts refer to it by containing it.
    name: str | None = None
    source: NodeSource = NodeSource.generate
    position: Position
    size: Size | None = None
    prompt: str = ""
    params: NodeParams
    # The take that downstream references resolve to. Null until the node has
    # produced an output; set automatically to the newest take on success.
    selected_output_id: OutputId | None = None
    # Workflow nodes (see contract/workflow.py): the step that made them,
    # and their number in its last run (1-based).
    workflow_step: str | None = None
    workflow_item: int | None = None
    created_at: Timestamp
    updated_at: Timestamp

    @model_validator(mode="after")
    def _params_match_kind(self) -> Node:
        _check_params_kind(self.kind, self.params)
        return self


class NodeCreate(ContractModel):
    kind: MediaKind
    position: Position
    # Fails with ``duplicate_name`` if another node has it. Blank means none.
    name: str | None = Field(default=None, max_length=NAME_MAX)
    size: Size | None = None
    prompt: str = Field(default="", max_length=20_000)
    # Omit to use the defaults for `kind`.
    params: NodeParams | None = None

    @model_validator(mode="after")
    def _params_match_kind(self) -> NodeCreate:
        _check_params_kind(self.kind, self.params)
        return self


class NodeUpdate(ContractModel):
    """Partial update: omitted fields are left as they are.

    ``kind`` can change; when it does and ``params`` is omitted, params reset
    to the new kind's defaults. Existing outputs stay attached to the node,
    but ``selected_output_id`` is cleared if it no longer matches the kind.
    Uploaded nodes cannot change kind or params.
    """

    kind: MediaKind | None = None
    # Explicit null (or blank) removes the name. Fails with ``duplicate_name``.
    name: str | None = Field(default=None, max_length=NAME_MAX)
    position: Position | None = None
    size: Size | None = None
    prompt: str | None = Field(default=None, max_length=20_000)
    params: NodeParams | None = None
    selected_output_id: OutputId | None = None

    @model_validator(mode="after")
    def _params_match_kind(self) -> NodeUpdate:
        _check_params_kind(self.kind, self.params)
        return self


# --- Edges (references) --------------------------------------------------------


class Edge(CompleteModel):
    """``target_node_id`` references ``source_node_id``: the source's selected
    output is one of the target's inputs."""

    id: EdgeId
    project_id: ProjectId
    source_node_id: NodeId
    target_node_id: NodeId
    # A workflow edge: feeds the target the source step's approved take.
    # Made and removed by the workflow only.
    workflow: bool = False
    created_at: Timestamp


class EdgeCreate(ContractModel):
    """Fails with ``self_reference``, ``duplicate_edge``, ``cycle``, or
    ``no_id`` when the source has no ID.

    Links follow prompts: creating one appends the source's ID to the
    target's prompt (and deleting one removes the mentions).
    """

    source_node_id: NodeId
    target_node_id: NodeId
