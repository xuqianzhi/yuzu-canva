"""Generation: jobs, the outputs they produce, and the stored media."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .common import (
    AssetId,
    CompleteModel,
    ContractModel,
    JobId,
    Language,
    MediaKind,
    NodeId,
    OutputId,
    ProjectId,
    Timestamp,
)
from .graph import NodeParams

# Reference limits per generated kind. Generate fails with `too_many_refs`
# past these. Text references are always allowed (they are inlined).
MAX_IMAGE_REFS = {MediaKind.text: 10, MediaKind.image: 10, MediaKind.video: 9}
MAX_VIDEO_REFS = {MediaKind.text: 0, MediaKind.image: 0, MediaKind.video: 3}


class Asset(CompleteModel):
    """A stored media file. Fetch the bytes from ``url``."""

    id: AssetId
    kind: MediaKind
    mime: str
    # Relative to the API origin, e.g. "/api/assets/ast_k4z9/content".
    url: str
    bytes: int = Field(ge=0)
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    created_at: Timestamp


class Output(CompleteModel):
    """One take produced by a node. Text outputs carry ``text``; image and
    video outputs carry ``asset``. Uploaded nodes' takes have no job."""

    id: OutputId
    node_id: NodeId
    job_id: JobId | None
    kind: MediaKind
    text: str | None = None
    asset: Asset | None = None
    created_at: Timestamp


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.succeeded, JobStatus.failed, JobStatus.canceled})


class Provider(StrEnum):
    openai = "openai"
    seedance = "seedance"


class Operation(StrEnum):
    """Which provider call a job makes. Chosen by the backend from the node's
    kind and the kinds of its references; the client never picks it."""

    text_generate = "text_generate"  # openai, text refs inlined, image refs as vision input
    image_generate = "image_generate"  # openai, no image refs
    image_edit = "image_edit"  # openai, one or more image refs
    video_generate = "video_generate"  # seedance, with or without image/video refs


class ResolvedRef(CompleteModel):
    """A reference as it was used by a job."""

    node_id: NodeId
    output_id: OutputId
    kind: MediaKind


class JobInput(CompleteModel):
    """Exactly what a job was run with, so any take can be reproduced."""

    prompt: str  # with mentions resolved
    params: NodeParams
    refs: list[ResolvedRef] = Field(default_factory=list)
    # Text jobs: the instructions given to the model before the prompt.
    system: str = ""
    # Unused: kept so older jobs still read. (Labels like "image 1" or
    # "图片1" now follow the prompt's own script.)
    language: Language = Language.en


class Job(CompleteModel):
    id: JobId
    project_id: ProjectId
    node_id: NodeId
    status: JobStatus
    provider: Provider
    operation: Operation
    input: JobInput
    # 0-1 when the provider reports progress, else null.
    progress: float | None = Field(default=None, ge=0, le=1)
    error: str | None = None
    output_id: OutputId | None = None
    # The provider's own id for the work (e.g. a Seedance task id), once
    # submitted. Lets a restarted backend resume polling instead of paying
    # twice, and helps when checking a job in the provider's console.
    provider_task_id: str | None = None
    # The seed a create request was sent with, saved before sending: finds
    # the provider's task if the backend stopped mid-send.
    provider_seed: int | None = None
    created_at: Timestamp
    started_at: Timestamp | None = None
    finished_at: Timestamp | None = None


class GenerateRequest(ContractModel):
    """Body of ``POST /api/nodes/{id}/generate``. Empty for now: the node's
    saved prompt and params are used, so save before generating."""
