"""Global assets: named images and videos that every new project starts with.

When a project is created, each global asset becomes an uploaded node on its
canvas (oldest first, down the left side), with its own copy of the file.
Changing or deleting a global asset later does not touch existing projects.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from .common import CompleteModel, ContractModel, MediaKind, Timestamp

GlobalAssetId = Annotated[str, Field(pattern=r"^gas_[A-Za-z0-9]+$", examples=["gas_k2m9"])]

# Where new projects put the nodes made from global assets (canvas units):
# a column down the left, clear of the menu bar, one node per step.
GLOBAL_NODE_X = 120
GLOBAL_NODE_Y = 60
GLOBAL_NODE_STEP = 500


class GlobalAsset(CompleteModel):
    id: GlobalAssetId
    # Required, unique among global assets (ignoring case and spacing); it
    # becomes the node's name in each new project.
    name: str
    kind: MediaKind
    mime: str
    # Relative to the API origin, e.g. "/api/global-assets/gas_k2m9/content".
    url: str
    bytes: int = Field(ge=0)
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None
    created_at: Timestamp


class GlobalAssetUpdate(ContractModel):
    name: str = Field(min_length=1, max_length=80)
