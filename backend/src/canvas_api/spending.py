"""What each user may spend on the model APIs: daily limits, a per-minute
rate for text calls, a cap on jobs waiting at once, and a switch that turns
every model call off.

Calls are counted when they are made, whether or not they succeed (the
provider usually bills them either way).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from .config import Limits
from .contract import ErrorCode, MediaKind
from .errors import ApiError
from .store import Store

_WORDS = {"text": "text calls", "image": "images", "video": "videos"}


def kind_of(kind: MediaKind) -> str:
    return kind.value


class Spending:
    def __init__(self, store: Store, limits: Limits, off: bool = False) -> None:
        self._store = store
        self._limits = limits
        self._off = off
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _daily(self, kind: str) -> int:
        return {
            "text": self._limits.text_per_day,
            "image": self._limits.images_per_day,
            "video": self._limits.videos_per_day,
        }[kind]

    def check_on(self) -> None:
        if self._off:
            raise ApiError(
                503, ErrorCode.generation_off, "generation is turned off for now; try later"
            )

    def charge(self, owner: str, kind: str, amount: int = 1) -> None:
        """Count `amount` calls of `kind` ("text", "image", "video"), or
        refuse (429) if that would pass a limit."""
        self.check_on()
        if amount <= 0:
            return
        if kind == "text":
            self._rate(owner, amount)
        limit = self._daily(kind)
        if limit:
            start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            used = self._store.usage_since(owner, start).get(kind, 0)
            if used + amount > limit:
                raise ApiError(
                    429,
                    ErrorCode.quota_exceeded,
                    f"daily limit reached: {used} of {limit} {_WORDS[kind]} used today "
                    "(resets at 00:00 UTC)",
                    {"kind": kind, "used": str(used), "limit": str(limit)},
                )
        self._store.record_usage(owner, kind, amount)

    def _rate(self, owner: str, amount: int) -> None:
        limit = self._limits.text_per_minute
        if not limit:
            return
        now = time.monotonic()
        with self._lock:
            recent = self._recent[owner]
            while recent and recent[0] < now - 60:
                recent.popleft()
            if len(recent) + amount > limit:
                raise ApiError(
                    429,
                    ErrorCode.quota_exceeded,
                    f"too many requests: at most {limit} a minute; wait a moment",
                    {"kind": "rate"},
                )
            recent.extend([now] * amount)

    def check_jobs(self, owner: str, adding: int) -> None:
        """Refuse (429) if `adding` more jobs would pass the waiting cap."""
        limit = self._limits.active_jobs
        if not limit:
            return
        active = self._store.active_job_count(owner)
        if active + adding > limit:
            raise ApiError(
                429,
                ErrorCode.quota_exceeded,
                f"{active} generations are already waiting or running (at most {limit}); "
                "wait for some to finish",
                {"kind": "jobs"},
            )
