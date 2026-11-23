"""The signed-in user."""

from __future__ import annotations

from .common import CompleteModel


class UsageCounts(CompleteModel):
    text: int
    image: int
    video: int


class UsageLine(CompleteModel):
    """Part of today's bill: what one person generated in one collection."""

    # Null once the collection is deleted (the usage still counts).
    collection_id: str | None = None
    collection_name: str | None = None
    # Who generated it (null if their account is gone).
    email: str | None = None
    used: UsageCounts


class Me(CompleteModel):
    """Who you're signed in as, and what you pay for today (UTC): everything
    generated in your collections, by you or your editors, against your
    daily limits (0 means no limit)."""

    email: str
    used_today: UsageCounts
    daily_limits: UsageCounts
    # ``used_today`` by collection and person, biggest first.
    breakdown: list[UsageLine] = []
