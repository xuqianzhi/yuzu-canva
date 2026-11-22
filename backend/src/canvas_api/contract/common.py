"""Shared building blocks for the API contract.

IDs are opaque strings with a type prefix, so a stray ID in a log or URL says
what it points at: prj_, nod_, edg_, out_, ast_, job_. Clients must treat them
as opaque and never parse them.

All timestamps are UTC, ISO 8601.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Base for every request/response body: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


def _all_fields_required(schema: dict) -> None:
    if "properties" in schema:
        schema["required"] = list(schema["properties"])


class CompleteModel(ContractModel):
    """A model that is always sent with every field present: responses, and
    small value objects (params, viewport) that clients send whole.

    Every field is marked required in the schema, so generated clients get
    `title: string` rather than `title?: string`. Python-side defaults stay,
    so the backend can still build these and accept partial input.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra=_all_fields_required)


ProjectId = Annotated[str, Field(pattern=r"^prj_[A-Za-z0-9]+$", examples=["prj_8f2k1"])]
NodeId = Annotated[str, Field(pattern=r"^nod_[A-Za-z0-9]+$", examples=["nod_a91x"])]
EdgeId = Annotated[str, Field(pattern=r"^edg_[A-Za-z0-9]+$", examples=["edg_3m7q"])]
OutputId = Annotated[str, Field(pattern=r"^out_[A-Za-z0-9]+$", examples=["out_x0p2"])]
AssetId = Annotated[str, Field(pattern=r"^ast_[A-Za-z0-9]+$", examples=["ast_k4z9"])]
JobId = Annotated[str, Field(pattern=r"^job_[A-Za-z0-9]+$", examples=["job_77ab"])]
MaterialId = Annotated[str, Field(pattern=r"^mat_[A-Za-z0-9]+$", examples=["mat_q2w8"])]

Timestamp = datetime


class Language(StrEnum):
    """The app's language: the UI's, and that of every prompt the backend
    writes for the models (the user's own text is sent as written)."""

    en = "en"
    zh = "zh"


# Text in each language, keyed by Language value ("en", "zh"). Readers fall
# back to English when a language is missing.
Localized = dict[str, str]


class MediaKind(StrEnum):
    """What a node produces, and what kind of thing an output is."""

    text = "text"
    image = "image"
    video = "video"


class NodeSource(StrEnum):
    """Where a node's outputs come from."""

    generate = "generate"  # a prompt and a model
    upload = "upload"  # a file placed from the project's materials


class Position(CompleteModel):
    """Top-left corner of a node, in canvas (world) coordinates."""

    x: float
    y: float


class Size(CompleteModel):
    """Node size in canvas coordinates. Null on a node means "auto"."""

    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Viewport(CompleteModel):
    """Saved pan and zoom of a project's canvas."""

    x: float = 0
    y: float = 0
    zoom: float = Field(default=1, gt=0)


class ErrorCode(StrEnum):
    not_found = "not_found"
    validation_error = "validation_error"
    # Creating the edge would make the reference graph cyclic.
    cycle = "cycle"
    # The edge already exists, or a node would reference itself.
    duplicate_edge = "duplicate_edge"
    self_reference = "self_reference"
    # Generate was called but a referenced node has no selected output yet.
    missing_ref_output = "missing_ref_output"
    # A reference's kind cannot feed this node's kind (e.g. video -> image).
    unsupported_ref = "unsupported_ref"
    # Too many references of one kind for the provider (see generation limits).
    too_many_refs = "too_many_refs"
    # The node already has a queued or running job.
    job_in_progress = "job_in_progress"
    # The job already finished, so it cannot be cancelled.
    job_finished = "job_finished"
    provider_error = "provider_error"
    # Another live node in the project already has this name.
    duplicate_name = "duplicate_name"
    # The source node has no ID, so nothing can refer to it.
    no_id = "no_id"
    # Uploaded nodes hold a file; they cannot generate.
    not_generatable = "not_generatable"
    # An upload that is not a supported image or video, or is too big.
    unsupported_media = "unsupported_media"
    too_large = "too_large"
    # Workflow nodes and edges are managed by the workflow: they can't be
    # deleted, retyped or connected by hand.
    workflow_locked = "workflow_locked"
    # A workflow step can't run yet: the step before has no approved take.
    workflow_blocked = "workflow_blocked"


class ErrorDetail(CompleteModel):
    code: ErrorCode
    message: str
    # Optional pointers at what is wrong, e.g. {"node_id": "nod_..."}.
    context: dict[str, str] = Field(default_factory=dict)


class ErrorResponse(CompleteModel):
    """Body of every non-2xx response."""

    error: ErrorDetail
