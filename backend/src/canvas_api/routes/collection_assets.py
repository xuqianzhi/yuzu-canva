from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..contract import (
    CollectionAsset,
    CollectionAssetId,
    CollectionAssetUpdate,
    CollectionId,
    ErrorCode,
    MediaKind,
)
from ..deps import FilesDep, StoreDep
from ..errors import ApiError, responses
from ..files import delete_all
from ..providers.media import UnsupportedMedia, sniff_upload
from .materials import read_upload

router = APIRouter(tags=["collection assets"])


@router.get(
    "/collections/{collection_id}/assets",
    operation_id="listCollectionAssets",
    responses=responses(404),
)
def list_collection_assets(
    collection_id: CollectionId, store: StoreDep
) -> list[CollectionAsset]:
    """The collection's assets, oldest first (the order new projects lay
    them out)."""
    return store.list_collection_assets(collection_id)


@router.post(
    "/collections/{collection_id}/assets",
    status_code=201,
    operation_id="uploadCollectionAsset",
    responses=responses(404, 409, 413, 415),
)
async def upload_collection_asset(
    collection_id: CollectionId,
    store: StoreDep,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form(max_length=80)],
) -> CollectionAsset:
    """Upload one image (PNG, JPEG, WebP) or video (MP4, MOV) with a name.

    Multipart fields ``file`` and ``name``. The name is required and unique
    in the collection (409 ``duplicate_name``). Every project created in the
    collection from now on starts with it as a node.
    """
    data = await read_upload(file)
    try:
        kind, mime, ext, width, height, duration = sniff_upload(data)
    except UnsupportedMedia as exc:
        raise ApiError(415, ErrorCode.unsupported_media, str(exc)) from exc
    return await run_in_threadpool(
        store.create_collection_asset,
        collection_id,
        name,
        MediaKind(kind),
        data,
        mime,
        ext,
        width=width,
        height=height,
        duration_s=duration,
    )


@router.patch(
    "/collection-assets/{asset_id}",
    operation_id="renameCollectionAsset",
    responses=responses(404, 409),
)
def rename_collection_asset(
    asset_id: CollectionAssetId, body: CollectionAssetUpdate, store: StoreDep
) -> CollectionAsset:
    """Rename it. Projects created earlier keep their node names."""
    return store.rename_collection_asset(asset_id, body.name)


@router.delete(
    "/collection-assets/{asset_id}",
    status_code=204,
    response_class=Response,
    operation_id="deleteCollectionAsset",
    responses=responses(404),
)
def delete_collection_asset(
    asset_id: CollectionAssetId, store: StoreDep, files: FilesDep
) -> None:
    """New projects stop getting it; projects made earlier keep their nodes."""
    delete_all(files, [store.delete_collection_asset(asset_id)])
