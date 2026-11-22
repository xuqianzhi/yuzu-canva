from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..contract import AssetId, ErrorCode
from ..deps import StoreDep
from ..errors import ApiError, responses

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get(
    "/{asset_id}/content",
    operation_id="getAssetContent",
    response_class=FileResponse,
    responses={
        200: {
            "description": "The media bytes. Supports HTTP Range for video seeking.",
            "content": {"image/*": {}, "video/*": {}},
        },
        **responses(404),
    },
)
def get_asset_content(asset_id: AssetId, store: StoreDep) -> FileResponse:
    asset, path = store.asset_file(asset_id)
    if not path.is_file():
        raise ApiError(404, ErrorCode.not_found, f"asset {asset_id} file is missing")
    # Assets never change once written, so browsers may cache them for good.
    return FileResponse(
        path,
        media_type=asset.mime,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
