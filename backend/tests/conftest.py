from __future__ import annotations

import asyncio
import base64
import os
import struct
import threading
import time
import uuid
import zlib
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from canvas_api.app import create_app
from canvas_api.config import LOCAL_DATABASE_URL, Settings
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


def make_settings(data_dir: Path, database_url: str, **overrides) -> Settings:
    return Settings(
        data_dir=data_dir,
        openai_api_key="test-key-not-real",
        openai_base_url="https://openai.invalid/v1",
        openai_image_model="test-model",
        openai_timeout_s=5,
        worker_concurrency=2,
        database_url=database_url,
        dev_auth=True,
        url_secret="test-url-signing-secret-0123456789",
        **overrides,
    )


# The default test user, and another one (for "can't see their things").
ALICE = "alice@example.com"
BOB = "bob@example.com"


def auth(email: str = ALICE) -> dict[str, str]:
    return {"Authorization": f"Bearer dev:{email}"}


def signed_in(app, email: str = ALICE) -> TestClient:
    """A test client that sends `email`'s dev sign-in with every request."""
    return TestClient(app, headers=auth(email))


def open_store(settings: Settings):
    """The app's store, opened directly (e.g. to change things between runs)."""
    from canvas_api.files import LocalFiles, UrlSigner
    from canvas_api.store import Store

    return Store(
        settings.database_url, LocalFiles(settings.data_dir), UrlSigner(settings.url_secret)
    )


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", LOCAL_DATABASE_URL)


@pytest.fixture
def database_url() -> Iterator[str]:
    """A fresh, empty Postgres schema for one test, dropped afterwards."""
    schema = f"t_{uuid.uuid4().hex[:16]}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
    try:
        yield f"{TEST_DATABASE_URL}?options=-csearch_path%3D{schema}"
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


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
def settings(data_dir: Path, database_url: str) -> Settings:
    return make_settings(data_dir, database_url)


@pytest.fixture
def client(
    settings: Settings,
    fake_image: FakeImageGenerator,
    fake_video: FakeVideo,
    fake_text: FakeTextModel,
) -> Iterator[TestClient]:
    generators = {
        Operation.image_generate: fake_image,
        Operation.image_edit: fake_image,
        Operation.video_generate: fake_video,
    }
    app = create_app(settings, generators, fake_text)
    with signed_in(app) as test_client:
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
