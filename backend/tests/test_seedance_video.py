"""The Seedance provider against a mocked Ark API."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import time
from pathlib import Path

import httpx
import pytest

from canvas_api.contract import MediaKind, Operation, VideoParams
from canvas_api.providers.base import GenerationRequest, ProviderError, RefFile
from canvas_api.providers.media import mp4_info
from canvas_api.providers.seedance_video import SeedanceVideoGenerator

BASE = "https://ark.test/api/v3"
TASKS = f"{BASE}/contents/generations/tasks"
VIDEO = (
    Path(__file__).resolve().parents[1] / "src/canvas_api/providers/fake_assets/portrait.mp4"
).read_bytes()


class FakeArk:
    """Scripted Ark: a queue of statuses for GET, records every request."""

    def __init__(self, statuses=("queued", "running", "succeeded")) -> None:
        self.statuses = list(statuses)
        self.requests: list[httpx.Request] = []
        self.post_responses: list[httpx.Response] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if request.method == "POST" and url == TASKS:
            if self.post_responses:
                return self.post_responses.pop(0)
            return httpx.Response(200, json={"id": "cgt-123"})
        if request.method == "GET" and url == f"{TASKS}/cgt-123":
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            body = {"id": "cgt-123", "status": status}
            if status == "succeeded":
                body["content"] = {"video_url": "https://tos.test/v.mp4?sig=1"}
            if status == "failed":
                body["error"] = {
                    "code": "OutputVideoSensitiveContentDetected",
                    "message": "nope",
                }
            return httpx.Response(200, json=body)
        if request.method == "GET" and url.startswith("https://tos.test/"):
            return httpx.Response(200, content=VIDEO)
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": {"code": "NotFound", "message": url}})

    def bodies(self, method: str) -> list:
        return [json.loads(r.content) for r in self.requests if r.method == method]


def generator(ark: FakeArk, key: str = "ark-test") -> SeedanceVideoGenerator:
    return SeedanceVideoGenerator(
        api_key=key,
        base_url=BASE,
        model="doubao-seedance-test",
        poll_interval_s=0,
        poll_timeout_s=5,
        transport=httpx.MockTransport(ark),
        backoff_s=0,
    )


def request(files=(), prompt="a fox running", **params) -> GenerationRequest:
    return GenerationRequest(
        operation=Operation.video_generate,
        prompt=prompt,
        params=VideoParams(**params),
        files=list(files),
    )


def ref(tmp_path: Path, node_id: str, kind: MediaKind, data: bytes) -> RefFile:
    path = tmp_path / f"{node_id}.bin"
    path.write_bytes(data)
    mime = "image/png" if kind == MediaKind.image else "video/mp4"
    return RefFile.from_path(node_id=node_id, kind=kind, path=path, mime=mime)


def test_text_to_video():
    ark = FakeArk()
    submitted = []
    req = request(ratio="16:9", duration_s=5, resolution="720p", generate_audio=False, seed=7)
    req = GenerationRequest(**{**req.__dict__, "on_submitted": submitted.append})
    result = asyncio.run(generator(ark).run(req))

    body = ark.bodies("POST")[0]
    assert body == {
        "model": "doubao-seedance-test",
        "content": [{"type": "text", "text": "a fox running"}],
        "resolution": "720p",
        "ratio": "16:9",
        "duration": 5,
        "generate_audio": False,
        "watermark": False,
        "seed": 7,
    }
    assert ark.requests[0].headers["authorization"] == "Bearer ark-test"
    assert submitted == ["cgt-123"]
    # The signed download URL gets no Ark credentials.
    download = next(r for r in ark.requests if "tos.test" in str(r.url))
    assert "authorization" not in download.headers
    assert result.kind == MediaKind.video and result.mime == "video/mp4"
    assert result.data == VIDEO
    assert (result.duration_s, result.width, result.height) == mp4_info(VIDEO)


def test_references_are_inlined_and_mentions_labelled(tmp_path):
    ark = FakeArk()
    files = [
        ref(tmp_path, "nod_a", MediaKind.image, b"IMG-A"),
        ref(tmp_path, "nod_v", MediaKind.video, b"VID-V"),
        ref(tmp_path, "nod_b", MediaKind.image, b"IMG-B"),
    ]
    prompt = "@{nod_a} meets @{nod_b}, moving like @{nod_v}"
    asyncio.run(generator(ark).run(request(files, prompt=prompt)))

    content = ark.bodies("POST")[0]["content"]
    assert content[0] == {"type": "text", "text": "图片1 meets 图片2, moving like 视频1"}

    def data_url(raw: bytes, mime: str) -> str:
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    assert content[1:] == [
        {
            "type": "image_url",
            "image_url": {"url": data_url(b"IMG-A", "image/png")},
            "role": "reference_image",
        },
        {
            "type": "image_url",
            "image_url": {"url": data_url(b"IMG-B", "image/png")},
            "role": "reference_image",
        },
        {
            "type": "video_url",
            "video_url": {"url": data_url(b"VID-V", "video/mp4")},
            "role": "reference_video",
        },
    ]


def test_failed_task_reports_ark_message():
    ark = FakeArk(statuses=("running", "failed"))
    with pytest.raises(ProviderError, match="Seedance task failed: nope"):
        asyncio.run(generator(ark).run(request()))


def test_resume_polls_without_submitting():
    ark = FakeArk(statuses=("succeeded",))
    req = GenerationRequest(**{**request().__dict__, "resume_task_id": "cgt-123"})
    result = asyncio.run(generator(ark).run(req))
    assert ark.bodies("POST") == []
    assert result.data == VIDEO


def test_missing_key():
    with pytest.raises(ProviderError, match="ARK_API_KEY"):
        asyncio.run(generator(FakeArk(), key="").run(request()))


def test_api_error_is_surfaced():
    ark = FakeArk()
    ark.post_responses = [
        httpx.Response(
            400, json={"error": {"code": "InvalidParameter", "message": "bad ratio"}}
        )
    ]
    with pytest.raises(ProviderError, match="Seedance 400 InvalidParameter: bad ratio"):
        asyncio.run(generator(ark).run(request()))


def test_post_is_not_retried_on_server_error():
    """A 5xx on create may still have made (and billed) the task."""
    ark = FakeArk()
    ark.post_responses = [httpx.Response(502, text="bad gateway")] * 3
    with pytest.raises(ProviderError, match="502"):
        asyncio.run(generator(ark).run(request()))
    assert len(ark.bodies("POST")) == 1


def test_post_is_retried_on_rate_limit():
    ark = FakeArk(statuses=("succeeded",))
    ark.post_responses = [httpx.Response(429, json={"error": {"code": "RateLimit"}})]
    asyncio.run(generator(ark).run(request()))
    assert len(ark.bodies("POST")) == 2


def test_too_large_reference(tmp_path):
    big = ref(tmp_path, "nod_a", MediaKind.image, b"x" * (10 * 1024 * 1024 + 1))
    with pytest.raises(ProviderError, match="at most 10 MiB"):
        asyncio.run(generator(FakeArk()).run(request([big])))


def test_cancel_while_queued_cancels_the_task():
    ark = FakeArk(statuses=("queued",))
    gen = SeedanceVideoGenerator(
        api_key="k",
        base_url=BASE,
        model="m",
        poll_interval_s=0.01,
        transport=httpx.MockTransport(ark),
        backoff_s=0,
    )

    async def scenario():
        task = asyncio.create_task(gen.run(request()))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert [r.method for r in ark.requests if r.method == "DELETE"] == ["DELETE"]


# --- lost create requests, retries, image shrinking ---------------------------


class LossyArk(FakeArk):
    """The first POST is sent but its answer is lost (like a dropped upload).

    `created` decides whether Ark made the task anyway; the listing shows it.
    """

    def __init__(self, created: bool) -> None:
        super().__init__(statuses=("succeeded",))
        self.created = created
        self.seed = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == TASKS and self.seed is None:
            body = json.loads(request.content)
            self.seed = body["seed"]
            self.requests.append(request)
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        if request.method == "GET" and url.startswith(f"{TASKS}?"):
            self.requests.append(request)
            items = [  # an unrelated recent task, then ours if it was created
                {
                    "id": "cgt-other",
                    "seed": 1,
                    "duration": 4,
                    "ratio": "9:16",
                    "resolution": "480p",
                    "created_at": int(time.time()),
                },
            ]
            if self.created:
                items.insert(
                    0,
                    {
                        "id": "cgt-123",
                        "seed": self.seed,
                        "duration": 4,
                        "ratio": "9:16",
                        "resolution": "480p",
                        "created_at": int(time.time()),
                    },
                )
            return httpx.Response(200, json={"items": items, "total": len(items)})
        return super().__call__(request)


def test_lost_create_answer_recovers_the_created_task():
    ark = LossyArk(created=True)
    submitted = []
    req = GenerationRequest(**{**request().__dict__, "on_submitted": submitted.append})
    result = asyncio.run(generator(ark).run(req))
    assert len(ark.bodies("POST")) == 1  # never sent twice
    assert submitted == ["cgt-123"]
    assert result.data == VIDEO
    listing = next(r for r in ark.requests if "page_num" in str(r.url))
    assert "filter.model=doubao-seedance-test" in str(listing.url)


def test_lost_create_without_a_task_says_retry_is_safe():
    ark = LossyArk(created=False)
    with pytest.raises(ProviderError, match="generating again is safe") as caught:
        asyncio.run(generator(ark).run(request()))
    assert "connection to Seedance dropped" in str(caught.value)
    assert len(ark.bodies("POST")) == 1


def test_a_seed_is_always_sent():
    ark = FakeArk()
    asyncio.run(generator(ark).run(request()))
    seed = ark.bodies("POST")[0]["seed"]
    assert isinstance(seed, int) and 0 <= seed < 2**32


def test_connect_errors_are_retried_even_for_post():
    """Nothing was sent, so a retry cannot create a second task."""
    ark = FakeArk(statuses=("succeeded",))
    failures = [httpx.ConnectError("[Errno 99] Cannot assign requested address")]

    def flaky(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and failures:
            raise failures.pop()
        return ark(req)

    gen = SeedanceVideoGenerator(
        api_key="k",
        base_url=BASE,
        model="m",
        poll_interval_s=0,
        transport=httpx.MockTransport(flaky),
        backoff_s=0,
    )
    assert asyncio.run(gen.run(request())).data == VIDEO
    assert len(ark.bodies("POST")) == 1


def test_reference_images_are_sent_as_compact_jpeg(tmp_path):
    from PIL import Image

    big = tmp_path / "big.png"
    Image.effect_noise((3000, 2000), 64).convert("RGBA").save(big)
    ark = FakeArk()
    files = [RefFile.from_path("nod_a", MediaKind.image, big, "image/png")]
    asyncio.run(generator(ark).run(request(files)))
    url = ark.bodies("POST")[0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    sent = base64.b64decode(url.split(",", 1)[1])
    with Image.open(io.BytesIO(sent)) as image:
        assert max(image.size) == 1024
    assert len(sent) < big.stat().st_size


def test_compact_image_rules():
    from PIL import Image

    from canvas_api.providers.media import compact_image

    def png(size, noise=False):
        out = io.BytesIO()
        image = Image.effect_noise(size, 64) if noise else Image.new("L", size, 128)
        image.convert("RGB").save(out, "PNG")
        return out.getvalue()

    # Too big: always scaled and sent as JPEG.
    data, mime = compact_image(png((2500, 1000)), "image/png")
    with Image.open(io.BytesIO(data)) as image:
        assert (mime, image.size) == ("image/jpeg", (1024, 410))
    # Small, and smaller as PNG than any JPEG would be: kept as is.
    tiny = png((16, 16))
    assert compact_image(tiny, "image/png") == (tiny, "image/png")
    # Small but noisy: the JPEG is smaller, so it wins.
    noisy = png((400, 300), noise=True)
    data, mime = compact_image(noisy, "image/png")
    assert mime == "image/jpeg" and len(data) < len(noisy)


def test_default_timeout_allows_slow_uploads():
    from canvas_api.config import Settings

    assert Settings.from_env().seedance_http_timeout_s == 900
    assert SeedanceVideoGenerator(api_key="k", base_url=BASE, model="m")._timeout.write == 900
