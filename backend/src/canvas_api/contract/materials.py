"""Materials: images and videos uploaded to a project, to place on the canvas."""

from __future__ import annotations

from .common import CompleteModel, ContractModel, MaterialId, Position, ProjectId, Timestamp
from .generation import Asset

# Uploads larger than this are refused with ``too_large``.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
# Accepted uploads, by sniffed content (not the file name).
UPLOAD_MIME_TYPES = ("image/png", "image/jpeg", "image/webp", "video/mp4", "video/quicktime")


class Material(CompleteModel):
    id: MaterialId
    project_id: ProjectId
    # The uploaded file's name, e.g. "fox.png".
    name: str
    asset: Asset
    created_at: Timestamp


class MaterialPlace(ContractModel):
    """Body of ``POST /api/materials/{id}/place``."""

    position: Position
