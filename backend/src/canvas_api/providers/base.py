from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..contract import MediaKind, NodeParams, Operation
from ..domain.graph import MENTION
from .media import compact_image

log = logging.getLogger(__name__)

# Every reference image sent to any provider is shrunk to JPEG first (long
# edge <= 1024 px, quality 80), as seedance-ui does: requests stay small and
# fast to upload, and 1024 px is plenty for a reference. The node's own file
# stored stays full size. Providers get reference bytes only through
# `RefFile.load()`, never by calling `read` themselves.
REF_IMAGE_MAX_EDGE = 1024
REF_IMAGE_JPEG_QUALITY = 80


class ProviderError(Exception):
    """A provider call failed. The message is shown to the user on the job."""


def reason(exc: BaseException) -> str:
    """Why a call failed, never blank: some network errors have no message of
    their own (an httpx.ConnectError can be empty), so fall back to what
    caused it, then to its type."""
    for candidate in (exc, exc.__cause__, exc.__context__):
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return type(exc).__name__


@dataclass(frozen=True)
class RefFile:
    """A referenced output's media, in the order the node references them.

    `read` fetches the stored bytes (from disk or the bucket); `name` is the
    file's name, e.g. "ast_x.png"."""

    node_id: str
    kind: MediaKind
    mime: str
    name: str
    read: Callable[[], bytes] = field(repr=False, compare=False)

    @classmethod
    def from_path(cls, node_id: str, kind: MediaKind, path: Path, mime: str) -> RefFile:
        return cls(node_id=node_id, kind=kind, mime=mime, name=path.name, read=path.read_bytes)

    def load(self) -> RefPayload:
        """The bytes to send: images compressed (see REF_IMAGE_MAX_EDGE),
        videos as they are."""
        try:
            data = self.read()
        except Exception as exc:  # noqa: BLE001 - shown to the user on the job
            raise ProviderError(f"a reference {self.kind.value} is missing: {exc}") from exc
        mime = self.mime
        if self.kind == MediaKind.image:
            before = len(data)
            data, mime = compact_image(
                data, mime, max_edge=REF_IMAGE_MAX_EDGE, quality=REF_IMAGE_JPEG_QUALITY
            )
            log.info(
                "reference image %s: %.2f MB -> %.2f MB",
                self.node_id,
                before / 1024 / 1024,
                len(data) / 1024 / 1024,
            )
        name = self.name
        if mime != self.mime:  # re-encoded as JPEG
            name = f"{Path(self.name).stem}.jpg"
        return RefPayload(data=data, mime=mime, filename=name)


@dataclass(frozen=True)
class RefPayload:
    """A reference file as it is sent to a provider."""

    data: bytes
    mime: str
    filename: str


@dataclass(frozen=True)
class GenerationRequest:
    operation: Operation
    prompt: str
    params: NodeParams
    files: list[RefFile] = field(default_factory=list)
    # Text jobs: instructions before the prompt, and the answer's structure.
    system: str = ""
    # Long-running providers (Seedance) report their task id through
    # `on_submitted`, so a restarted worker can pass it back as
    # `resume_task_id` and keep polling instead of submitting (and paying)
    # again.
    resume_task_id: str | None = None
    on_submitted: Callable[[str], None] | None = field(default=None, compare=False)
    # The seed (and Unix time) a create request is about to be sent with,
    # saved first through `on_sending`: if the backend stops mid-send, the
    # restarted worker passes them back as `resume_seed` / `resume_since` and
    # the provider looks the task up instead of sending it again (see
    # providers/billing_safety.py).
    resume_seed: int | None = None
    resume_since: float | None = None
    on_sending: Callable[[int, float], None] | None = field(default=None, compare=False)


@dataclass(frozen=True)
class GenerationResult:
    kind: MediaKind
    text: str | None = None
    data: bytes | None = None
    mime: str | None = None
    ext: str | None = None
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None


def label_mentions(prompt: str, files: list[RefFile], label: Callable[[int], str]) -> str:
    """Replace each ``@{node id}`` mention of a referenced file with a label
    for its position, e.g. ``label=lambda n: f"image {n}"`` (1-based).

    Mentions of nodes that are not among `files` are left alone (text
    references were already inlined by the planner).
    """
    numbers = {f.node_id: i for i, f in enumerate(files, start=1)}

    def replace(match: re.Match[str]) -> str:
        number = numbers.get(match.group(1))
        return label(number) if number else match.group(0)

    return MENTION.sub(replace, prompt)


class Generator(Protocol):
    async def run(self, request: GenerationRequest) -> GenerationResult: ...
