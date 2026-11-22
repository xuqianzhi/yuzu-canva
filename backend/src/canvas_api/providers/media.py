"""Sniff image type and size from bytes, without an imaging library."""

from __future__ import annotations

import io
import struct

from PIL import Image, ImageOps, UnidentifiedImageError


def sniff_image(data: bytes) -> tuple[str, str, int | None, int | None]:
    """Return (mime, extension, width, height). Size is None when unknown."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "image/png", "png", width, height
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg", "jpg", *_jpeg_size(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp", None, None
    return "application/octet-stream", "bin", None, None


def _jpeg_size(data: bytes) -> tuple[int | None, int | None]:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None, None
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return None, None


def mp4_info(data: bytes) -> tuple[float | None, int | None, int | None]:
    """(duration in seconds, width, height) from an MP4's moov box.

    Reads mvhd for the duration and the first video track's tkhd for the
    size. Returns Nones for anything it cannot find.
    """
    duration: float | None = None
    width = height = None

    def boxes(start: int, end: int):
        i = start
        while i + 8 <= end:
            size, kind = struct.unpack(">I4s", data[i : i + 8])
            header = 8
            if size == 1 and i + 16 <= end:
                size = struct.unpack(">Q", data[i + 8 : i + 16])[0]
                header = 16
            elif size == 0:
                size = end - i
            if size < header or i + size > end:
                return
            yield kind, i + header, i + size
            i += size

    try:
        for kind, body, end in boxes(0, len(data)):
            if kind != b"moov":
                continue
            for inner, ibody, iend in boxes(body, end):
                if inner == b"mvhd":
                    version = data[ibody]
                    if version == 1:
                        timescale, length = struct.unpack(">IQ", data[ibody + 20 : ibody + 32])
                    else:
                        timescale, length = struct.unpack(">II", data[ibody + 12 : ibody + 20])
                    if timescale:
                        duration = round(length / timescale, 3)
                elif inner == b"trak" and width is None:
                    for leaf, lbody, _ in boxes(ibody, iend):
                        if leaf != b"tkhd":
                            continue
                        offset = lbody + (88 if data[lbody] == 1 else 76)
                        w, h = struct.unpack(">II", data[offset : offset + 8])
                        if w and h:  # 16.16 fixed point; audio tracks are 0x0
                            width, height = w >> 16, h >> 16
    except (struct.error, IndexError):
        pass
    return duration, width, height


def compact_image(
    data: bytes, mime: str, max_edge: int = 1024, quality: int = 80
) -> tuple[bytes, str]:
    """Shrink an image for upload: long edge <= max_edge, re-encoded as JPEG.

    An image that had to be scaled down is always sent as the JPEG. One that
    already fits keeps whichever is smaller, itself or the JPEG (as
    seedance-ui does). Unreadable data is returned as is. Alpha is flattened
    onto white, since JPEG has none.
    """
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened)
            scaled = max(image.size) > max_edge
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                flat = Image.new("RGB", image.size, (255, 255, 255))
                flat.paste(image, mask=image.getchannel("A"))
                image = flat
            elif image.mode != "RGB":
                image = image.convert("RGB")
            out = io.BytesIO()
            image.save(out, "JPEG", quality=quality, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError):
        return data, mime
    jpeg = out.getvalue()
    return (jpeg, "image/jpeg") if scaled or len(jpeg) < len(data) else (data, mime)


class UnsupportedMedia(ValueError):
    """An upload that is not a supported image or video."""


_IMAGE_FORMATS = {
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
    "WEBP": ("image/webp", "webp"),
}


def sniff_upload(data: bytes) -> tuple[str, str, str, int | None, int | None, float | None]:
    """Identify an uploaded file by its content.

    Returns (kind, mime, extension, width, height, duration_s), where kind is
    "image" or "video". Raises UnsupportedMedia for anything else.
    """
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        duration, width, height = mp4_info(data)
        if brand == b"qt  ":
            return "video", "video/quicktime", "mov", width, height, duration
        return "video", "video/mp4", "mp4", width, height, duration
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format or ""
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnsupportedMedia("not a PNG, JPEG or WebP image, or an MP4/MOV video") from exc
    if fmt not in _IMAGE_FORMATS:
        raise UnsupportedMedia(
            f"{fmt or 'this'} images are not supported; use PNG, JPEG or WebP"
        )
    mime, ext = _IMAGE_FORMATS[fmt]
    return "image", mime, ext, width, height, None
