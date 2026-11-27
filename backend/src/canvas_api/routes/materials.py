from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..contract import (
    MAX_UPLOAD_BYTES,
    ErrorCode,
    Material,
    MaterialId,
    MaterialPlace,
    MediaKind,
    Node,
    ProjectId,
)
from ..deps import FilesDep, StoreDep
from ..errors import ApiError, responses
from ..files import delete_all
from ..providers.media import UnsupportedMedia, sniff_upload

router = APIRouter(tags=["materials"])


async def read_upload(file: UploadFile) -> bytes:
    """The whole upload, refusing it (413 ``too_large``) past the size limit."""
    chunks, size = [], 0
    while chunk := await file.read(1 << 20):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise ApiError(
                413,
                ErrorCode.too_large,
                f"files can be at most {MAX_UPLOAD_BYTES // 1024 // 1024} MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get(
    "/projects/{project_id}/materials",
    operation_id="listMaterials",
    responses=responses(404),
)
def list_materials(project_id: ProjectId, store: StoreDep) -> list[Material]:
    """The project's uploaded images and videos, newest first."""
    return store.list_materials(project_id)


@router.post(
    "/projects/{project_id}/materials",
    status_code=201,
    operation_id="uploadMaterial",
    responses=responses(404, 413, 415),
)
async def upload_material(
    project_id: ProjectId, store: StoreDep, file: Annotated[UploadFile, File()]
) -> Material:
    """Upload one image (PNG, JPEG, WebP) or video (MP4, MOV), multipart field ``file``.

    The type comes from the file's content, not its name. Fails with
    ``unsupported_media`` (415) or ``too_large`` (413).
    """
    data = await read_upload(file)
    try:
        kind, mime, ext, width, height, duration = sniff_upload(data)
    except UnsupportedMedia as exc:
        raise ApiError(415, ErrorCode.unsupported_media, str(exc)) from exc
    name = (file.filename or f"upload.{ext}").replace("/", "_").strip()[:200]
    return await run_in_threadpool(
        store.create_material,
        project_id,
        name,
        MediaKind(kind),
        data,
        mime,
        ext,
        width=width,
        height=height,
        duration_s=duration,
    )


@router.delete(
    "/materials/{material_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteMaterial",
    responses=responses(404),
)
def delete_material(material_id: MaterialId, store: StoreDep, files: FilesDep) -> None:
    """Remove it from the library. Nodes placed from it are unaffected."""
    delete_all(files, [store.delete_material(material_id)])


@router.post(
    "/materials/{material_id}/place",
    status_code=201,
    operation_id="placeMaterial",
    responses=responses(404),
)
def place_material(material_id: MaterialId, body: MaterialPlace, store: StoreDep) -> Node:
    """Put a material on the canvas as an uploaded node.

    The node is named after the file (made unique), and its single take is the
    file, already selected, so it can be used as another node's input at once.
    Prompts that already mention that name are linked to it (reload the graph
    for the new edges).
    """
    return store.place_material(material_id, body.position)
