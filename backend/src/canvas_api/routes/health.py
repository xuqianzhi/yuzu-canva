from __future__ import annotations

from typing import Literal

from fastapi import APIRouter

from ..contract import CompleteModel

router = APIRouter(tags=["health"])


class Health(CompleteModel):
    # Lets launchers tell this API apart from anything else on the port.
    app: Literal["yuzu-canva"] = "yuzu-canva"
    status: Literal["ok"] = "ok"
    version: str


@router.get("/health", operation_id="getHealth")
def get_health() -> Health:
    from .. import __version__

    return Health(version=__version__)
