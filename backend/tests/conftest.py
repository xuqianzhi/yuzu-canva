from __future__ import annotations

import asyncio
import base64
import struct
import threading
import time
import zlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from canvas_api.app import create_app
from canvas_api.config import Settings
from canvas_api.contract import MediaKind, Operation
from canvas_api.providers.base import GenerationRequest, GenerationResult, ProviderError
from canvas_api.providers.fake import FakeTextModel


def tiny_png(width: int = 2, height: int = 3) -> bytes:
    """A valid PNG of the given size (all black)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\x00" * width * 3 for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


PNG = tiny_png()
PNG_B64 = base64.b64encode(PNG).decode()


class FakeImageGenerator:
    """Stands in for OpenAI. Close `gate` to hold jobs in 'running'."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.gate.set()
        self.fail_with: str | None = None
        self.requests: list[GenerationRequest] = []

    async def run(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        if self.fail_with:
            raise ProviderError(self.fail_with)
        return GenerationResult(
            kind=MediaKind.image, data=PNG, mime="image/png", ext="png", width=2, height=3
        )


class FakeVideo:
    """Stands in for Seedance: reports a task id, resumable like the real one."""

    resumable = True

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.gate.set()
        self.requests: list[GenerationRequest] = []

    async def run(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if request.resume_task_id is None and request.on_submitted:
            request.on_submitted(f"cgt-{len(self.requests)}")
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        return GenerationResult(
            kind=MediaKind.video, data=b"MP4", mime="video/mp4", ext="mp4", duration_s=4
        )


def make_settings(data_dir: Path) -> Settings:
    return Settings(
        data_dir=data_dir,
        openai_api_key="test-key-not-real",
        openai_base_url="https://openai.invalid/v1",
        openai_image_model="test-model",
        openai_timeout_s=5,
        worker_concurrency=2,
    )


@pytest.fixture
def fake_image() -> FakeImageGenerator:
    return FakeImageGenerator()


@pytest.fixture
def fake_video() -> FakeVideo:
    return FakeVideo()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def fake_text() -> FakeTextModel:
    return FakeTextModel()


@pytest.fixture
def client(
    data_dir: Path,
    fake_image: FakeImageGenerator,
    fake_video: FakeVideo,
    fake_text: FakeTextModel,
) -> Iterator[TestClient]:
    generators = {
        Operation.image_generate: fake_image,
        Operation.image_edit: fake_image,
        Operation.video_generate: fake_video,
    }
    app = create_app(make_settings(data_dir), generators, fake_text)
    with TestClient(app) as test_client:
        yield test_client


def wait_for_job(client: TestClient, job_id: str, timeout: float = 5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "canceled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} still {job['status']} after {timeout}s")


def wait_for_status(client: TestClient, job_id: str, status: str, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.get(f"/api/jobs/{job_id}").json()["status"] == status:
            return
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never reached {status}")
