"""Offline stand-ins for the providers, for working on the UI.

Enabled with CANVAS_FAKE_GENERATORS=1. Waits a moment, then returns a PNG:

- no references: one solid color derived from the prompt, so different
  prompts look different and the same prompt is stable;
- with image references: vertical stripes, one per reference (its color),
  then the prompt's color -- so you can see which references were used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

from ..contract import ImageParams, MediaKind, VideoParams
from .base import GenerationRequest, GenerationResult
from .media import mp4_info

_SIZES = {"1024x1024": (512, 512), "1536x1024": (768, 512), "1024x1536": (512, 768)}

RGB = tuple[int, int, int]


def _chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def striped_png(width: int, height: int, colors: list[RGB]) -> bytes:
    """Vertical stripes of equal width, left to right."""
    row = bytearray(b"\x00")
    for x in range(width):
        row += bytes(colors[min(x * len(colors) // width, len(colors) - 1)])
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(row) * height, 9))
        + _chunk(b"IEND", b"")
    )


def solid_png(width: int, height: int, rgb: RGB) -> bytes:
    return striped_png(width, height, [rgb])


def color_of(text: bytes) -> RGB:
    digest = hashlib.sha256(text).digest()
    return (64 + digest[0] % 160, 64 + digest[1] % 160, 64 + digest[2] % 160)


def first_pixel(png: bytes) -> RGB | None:
    """Top-left color of an 8-bit RGB/RGBA PNG whose first row is unfiltered
    (true of the PNGs made here); None for anything else."""
    try:
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            return None
        _, _, depth, color_type = struct.unpack(">IIBB", png[16:26])
        if depth != 8 or color_type not in (2, 6):
            return None
        idat, i = b"", 8
        while i < len(png):
            length = struct.unpack(">I", png[i : i + 4])[0]
            tag = png[i + 4 : i + 8]
            if tag == b"IDAT":
                idat += png[i + 8 : i + 8 + length]
            i += 12 + length
        raw = zlib.decompressobj().decompress(idat, 8)
        if raw[0] != 0:  # filtered row
            return None
        return raw[1], raw[2], raw[3]
    except (struct.error, zlib.error, IndexError):
        return None


class FakeImageGenerator:
    def __init__(self, delay_s: float = 2.0) -> None:
        self._delay_s = delay_s

    async def run(self, request: GenerationRequest) -> GenerationResult:
        await asyncio.sleep(self._delay_s)
        params = request.params
        size = params.size if isinstance(params, ImageParams) else "auto"
        width, height = _SIZES.get(size, (512, 512))

        colors: list[RGB] = []
        for ref in request.files:
            if ref.kind != MediaKind.image:
                continue
            data = ref.read()
            colors.append(first_pixel(data) or color_of(data))
        colors.append(color_of(request.prompt.encode()))

        return GenerationResult(
            kind=MediaKind.image,
            data=striped_png(width, height, colors),
            mime="image/png",
            ext="png",
            width=width,
            height=height,
        )


_FAKE_VIDEOS = Path(__file__).with_name("fake_assets")


class FakeVideoGenerator:
    """Returns a 3-second test pattern (landscape or portrait by ratio)."""

    def __init__(self, delay_s: float = 4.0) -> None:
        self._delay_s = delay_s

    async def run(self, request: GenerationRequest) -> GenerationResult:
        await asyncio.sleep(self._delay_s)
        params = request.params
        ratio = params.ratio if isinstance(params, VideoParams) else "16:9"
        wide = ratio in ("21:9", "16:9", "4:3")
        data = (_FAKE_VIDEOS / ("landscape.mp4" if wide else "portrait.mp4")).read_bytes()
        duration, width, height = mp4_info(data)
        return GenerationResult(
            kind=MediaKind.video,
            data=data,
            mime="video/mp4",
            ext="mp4",
            width=width,
            height=height,
            duration_s=duration,
        )


class FakeTextModel:
    """Answers instantly from what it was asked, in the requested shape, so
    the workflow can be tried and tested offline. Records every call."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self._delay_s = delay_s
        self.calls: list[dict] = []

    async def complete(self, system, messages, spec=None, images=None) -> str:
        await asyncio.sleep(self._delay_s)
        self.calls.append(
            {"system": system, "messages": messages, "spec": spec, "images": images or []}
        )
        last = messages[-1]["content"]
        name = spec.name if spec is not None else "text"
        if name == "run":
            shape = spec.schema["properties"]["items"]
            texts = [f"Result {n}: {last[-80:]}" for n in range(1, shape["maxItems"] + 1)]
            fields = shape["items"].get("properties", {})
            if not fields:
                return json.dumps({"items": texts})
            # Prompts naming references: each says it uses all of them.
            ids = re.findall(r'<reference id="([^"]+)"', last)
            items = []
            for n, content in enumerate(texts, 1):
                item: dict = {"content": content}
                if "uses" in fields:
                    item["uses"] = ids
                if "seconds" in fields:  # videos: 5 s, 6 s, ...
                    item["seconds"] = 4 + n
                if "prompt" in fields:  # text results: the prompt that makes each
                    item["prompt"] = f"Prompt {n}: {last[-60:]}"
                items.append(item)
            return json.dumps({"items": items})
        if name == "edit":
            # The current text, marked as edited (a video keeps a length of 8 s).
            found = re.search(r"<current>\n?(.*?)\n?</current>", last, re.S)
            answer: dict = {"content": f"{found.group(1) if found else ''} (edited)".strip()}
            if "seconds" in spec.schema["properties"]:
                answer["seconds"] = 8
            return json.dumps(answer)
        return f"[fake text] {last[-300:]}"
