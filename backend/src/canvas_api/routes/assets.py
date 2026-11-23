"""Media files, by signed link (see files.UrlSigner): no sign-in header, as
<img> and <video> tags can't send one. Files on disk are served here; files
in a bucket are a redirect to a short-lived Cloud Storage link."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse, Response

from ..contract import AssetId, CollectionAssetId, ErrorCode
from ..deps import StoreDep
from ..errors import ApiError, responses
from ..files import IMMUTABLE

router = APIRouter(tags=["assets"])

_CONTENT = {
    200: {
        "description": "The media bytes. Supports HTTP Range for video seeking.",
        "content": {"image/*": {}, "video/*": {}},
    },
    307: {"description": "Redirect to the file in Cloud Storage."},
    **responses(404),
}

Expiry = Annotated[int, Query(alias="e")]
Signature = Annotated[str, Query(alias="s", max_length=64)]


def _serve(store, kind: str, id_: str, key: str, mime: str, expires: int, sig: str) -> Response:
    if not store.signer.check(kind, id_, expires, sig):
        # Expired or forged: the page reloads its data to get fresh links.
        raise ApiError(404, ErrorCode.not_found, "this media link expired; reload the page")
    url = store.files.download_url(key)
    if url is not None:
        return RedirectResponse(url, status_code=307, headers={"Cache-Control": "no-store"})
    path = store.files.local_path(key)
    if path is None or not path.is_file():
        raise ApiError(404, ErrorCode.not_found, f"{id_}: the file is missing")
    return FileResponse(path, media_type=mime, headers={"Cache-Control": IMMUTABLE})


@router.get(
    "/assets/{asset_id}/content",
    operation_id="getAssetContent",
    response_class=FileResponse,
    responses=_CONTENT,
)
async def get_asset_content(
    asset_id: AssetId, store: StoreDep, e: Expiry, s: Signature
) -> Response:
    asset, key = await run_in_threadpool(store.asset_file, asset_id)
    return await run_in_threadpool(_serve, store, "assets", asset_id, key, asset.mime, e, s)


@router.get(
    "/collection-assets/{asset_id}/content",
    operation_id="getCollectionAssetContent",
    response_class=FileResponse,
    responses=_CONTENT,
)
async def get_collection_asset_content(
    asset_id: CollectionAssetId, store: StoreDep, e: Expiry, s: Signature
) -> Response:
    asset, key = await run_in_threadpool(store.collection_asset_file, asset_id)
    return await run_in_threadpool(
        _serve, store, "collection-assets", asset_id, key, asset.mime, e, s
    )
