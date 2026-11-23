from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from ..contract import Me, UsageCounts
from ..deps import SettingsDep, StoreDep, UserDep
from ..errors import responses

router = APIRouter(tags=["me"])


@router.get("/me", operation_id="getMe", responses=responses(401, 403))
def get_me(store: StoreDep, user: UserDep, settings: SettingsDep) -> Me:
    """Who you're signed in as (401 if not, 403 if not on the allowlist),
    and what you pay for today (everything generated in your collections,
    by anyone) against your limits."""
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = store.usage_since(user.id, start)
    limits = settings.limits
    return Me(
        email=user.email,
        used_today=UsageCounts(
            text=used.get("text", 0), image=used.get("image", 0), video=used.get("video", 0)
        ),
        daily_limits=UsageCounts(
            text=limits.text_per_day, image=limits.images_per_day, video=limits.videos_per_day
        ),
        breakdown=store.usage_breakdown(user.id, start),
    )
