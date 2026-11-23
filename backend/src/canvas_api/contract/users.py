"""The signed-in user."""

from __future__ import annotations

from .common import CompleteModel


class UsageCounts(CompleteModel):
    text: int
    image: int
    video: int


class Me(CompleteModel):
    """Who you're signed in as, and what you used today (UTC) against your
    daily limits (0 means no limit)."""

    email: str
    used_today: UsageCounts
    daily_limits: UsageCounts
