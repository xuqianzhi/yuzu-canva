"""The OpenAI image provider against a mocked HTTP transport."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from canvas_api.contract import ImageParams, MediaKind, Operation
from canvas_api.providers.base import GenerationRequest, ProviderError, RefFile, label_mentions
from canvas_api.providers.openai_image import OpenAIImageGenerator

from .conftest import PNG, PNG_B64

REQUEST = GenerationRequest(
    operation=Operation.image_generate,
    prompt="a fox",
    params=ImageParams(size="1024x1536", quality="high"),
)


def generator(handler, api_key: str = "sk-test") -> OpenAIImageGenerator:
    return OpenAIImageGenerator(
        api_key=api_key,
        base_url="https://openai.test/v1",
        model="gpt-image-2",
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )


def run(gen: OpenAIImageGenerator):
    return asyncio.run(gen.run(REQUEST))


def test_success():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"b64_json": PNG_B64}]})

    result = run(generator(handler))
    assert seen["url"] == "https://openai.test/v1/images/generations"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"] == {
        "model": "gpt-image-2",
        "prompt": "a fox",
        "n": 1,
        "size": "1024x1536",
        "quality": "high",
    }
    assert result.data == PNG
    assert (result.mime, result.ext, result.width, result.height) == ("image/png", "png", 2, 3)


def test_api_error_message_is_surfaced():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Your prompt was rejected"}})

    with pytest.raises(ProviderError, match="OpenAI 400: Your prompt was rejected"):
        run(generator(handler))


def test_missing_key():
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        run(generator(lambda r: httpx.Response(200), api_key=""))


def test_response_without_image():
    with pytest.raises(ProviderError, match="no image"):
        run(generator(lambda r: httpx.Response(200, json={"data": []})))


def test_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(ProviderError, match="could not reach OpenAI"):
        run(generator(handler))


def test_fake_generator_makes_a_valid_png_per_prompt():
    from canvas_api.providers.fake import FakeImageGenerator
    from canvas_api.providers.media import sniff_image

    fake = FakeImageGenerator(delay_s=0)
    wide = GenerationRequest(
        operation=Operation.image_generate, prompt="a", params=ImageParams(size="1536x1024")
    )
    result = asyncio.run(fake.run(wide))
    assert sniff_image(result.data) == ("image/png", "png", 768, 512)
    other = asyncio.run(
        fake.run(GenerationRequest(Operation.image_generate, "b", ImageParams()))
    )
    assert other.data != result.data


def test_edit_sends_reference_images_as_multipart(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"AAAA")
    b.write_bytes(b"BBBB")
    request = GenerationRequest(
        operation=Operation.image_edit,
        prompt="put @{nod_a} in @{nod_b}, keep @{nod_zz}",
        params=ImageParams(quality="low"),
        files=[
            RefFile(node_id="nod_a", kind=MediaKind.image, path=a, mime="image/png"),
            RefFile(node_id="nod_b", kind=MediaKind.image, path=b, mime="image/png"),
        ],
    )
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["type"] = req.headers["content-type"]
        seen["body"] = req.content
        return httpx.Response(200, json={"data": [{"b64_json": PNG_B64}]})

    result = asyncio.run(generator(handler).run(request))
    assert seen["url"] == "https://openai.test/v1/images/edits"
    assert seen["type"].startswith("multipart/form-data")
    body = seen["body"]
    assert body.count(b'name="image[]"') == 2
    assert body.index(b"AAAA") < body.index(b"BBBB")  # reference order is kept
    assert b"put image 1 in image 2, keep @{nod_zz}" in body
    assert b'name="model"' in body and b"gpt-image-2" in body
    assert b'name="quality"' in body and b"low" in body
    assert result.data == PNG


def test_edit_with_missing_reference_file(tmp_path):
    request = GenerationRequest(
        operation=Operation.image_edit,
        prompt="x",
        params=ImageParams(),
        files=[RefFile("nod_a", MediaKind.image, tmp_path / "gone.png", "image/png")],
    )
    with pytest.raises(ProviderError, match="missing on disk"):
        asyncio.run(generator(lambda r: httpx.Response(200)).run(request))


def test_label_mentions():
    files = [RefFile("nod_b", MediaKind.image, Path("b"), "image/png")]
    assert label_mentions("@{nod_a} @{nod_b}", files, lambda n: f"[{n}]") == "@{nod_a} [1]"


def test_fake_edit_stripes_reference_colors(tmp_path):
    from canvas_api.providers.fake import FakeImageGenerator, first_pixel, solid_png

    red = tmp_path / "red.png"
    red.write_bytes(solid_png(4, 4, (200, 10, 10)))
    request = GenerationRequest(
        operation=Operation.image_edit,
        prompt="p",
        params=ImageParams(),
        files=[RefFile("nod_a", MediaKind.image, red, "image/png")],
    )
    result = asyncio.run(FakeImageGenerator(delay_s=0).run(request))
    assert first_pixel(result.data) == (200, 10, 10)  # leftmost stripe is the reference


def test_edit_sends_compressed_reference_images(tmp_path):
    """Reference images go to OpenAI compressed, as to every provider:
    JPEG, long edge <= 1024 px. The file on disk is untouched."""
    import io
    from email.parser import BytesParser
    from email.policy import HTTP

    from PIL import Image

    big = tmp_path / "big.png"
    Image.effect_noise((2500, 1000), 64).convert("RGB").save(big, "PNG")
    original = big.read_bytes()
    request = GenerationRequest(
        operation=Operation.image_edit,
        prompt="restyle @{nod_a}",
        params=ImageParams(),
        files=[RefFile(node_id="nod_a", kind=MediaKind.image, path=big, mime="image/png")],
    )
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["type"] = req.headers["content-type"]
        seen["body"] = req.content
        return httpx.Response(200, json={"data": [{"b64_json": PNG_B64}]})

    asyncio.run(generator(handler).run(request))
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + seen["type"].encode() + b"\r\n\r\n" + seen["body"]
    )
    [part] = [
        p
        for p in message.iter_parts()
        if p.get_param("name", header="content-disposition") == "image[]"
    ]
    assert part.get_filename() == "big.jpg"
    assert part.get_content_type() == "image/jpeg"
    sent = part.get_payload(decode=True)
    with Image.open(io.BytesIO(sent)) as image:
        assert (image.format, max(image.size)) == ("JPEG", 1024)
    assert len(sent) < len(original)
    assert big.read_bytes() == original
