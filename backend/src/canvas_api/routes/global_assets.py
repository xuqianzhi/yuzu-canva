from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..contract import ErrorCode, GlobalAsset, GlobalAssetId, GlobalAssetUpdate, MediaKind
from ..deps import FilesDep, StoreDep, UserDep
from ..errors import ApiError, responses
from ..files import delete_all
from ..providers.media import UnsupportedMedia, sniff_upload
from .materials import read_upload

router = APIRouter(prefix="/global-assets", tags=["global assets"])


@router.get("", operation_id="listGlobalAssets", responses=responses())
def list_global_assets(store: StoreDep, user: UserDep) -> list[GlobalAsset]:
    """Your global assets, oldest first (the order new projects lay them out)."""
    return store.list_global_assets(user.id)


@router.post(
    "",
    status_code=201,
    operation_id="uploadGlobalAsset",
    responses=responses(409, 413, 415),
)
async def upload_global_asset(
    store: StoreDep,
    user: UserDep,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form(max_length=80)],
) -> GlobalAsset:
    """Upload one image (PNG, JPEG, WebP) or video (MP4, MOV) with a name.

    Multipart fields ``file`` and ``name``. The name is required and unique
    among global assets (409 ``duplicate_name``). Every project created from
    now on starts with it as a node.
    """
    data = await read_upload(file)
    try:
        kind, mime, ext, width, height, duration = sniff_upload(data)
    except UnsupportedMedia as exc:
        raise ApiError(415, ErrorCode.unsupported_media, str(exc)) from exc
    return await run_in_threadpool(
        store.create_global_asset,
        user.id,
        name,
        MediaKind(kind),
        data,
        mime,
        ext,
        width=width,
        height=height,
        duration_s=duration,
    )


@router.patch("/{asset_id}", operation_id="renameGlobalAsset", responses=responses(404, 409))
def rename_global_asset(
    asset_id: GlobalAssetId, body: GlobalAssetUpdate, store: StoreDep
) -> GlobalAsset:
    """Rename it. Projects created earlier keep their node names."""
    return store.rename_global_asset(asset_id, body.name)


@router.delete(
    "/{asset_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteGlobalAsset",
    responses=responses(404),
)
def delete_global_asset(asset_id: GlobalAssetId, store: StoreDep, files: FilesDep) -> None:
    """New projects stop getting it; projects made earlier keep their nodes."""
    delete_all(files, [store.delete_global_asset(asset_id)])
