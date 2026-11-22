"""SQLite persistence. Every method returns contract models.

One connection, guarded by a lock: routes run in a thread pool and the job
worker runs on the event loop, and every call here is short. Swap for
Postgres later behind the same methods.

The store is split by area into mixins; ``Store`` puts them together.
"""

from __future__ import annotations

from .base import PURGE_AFTER, WORKFLOW_HANDLE, StoreBase, now
from .chat import ChatMixin
from .graph import GraphMixin
from .jobs import JobsMixin
from .media import MediaMixin
from .migrations import MigrationsMixin
from .projects import ProjectsMixin
from .workflow import WorkflowMixin


class Store(
    MigrationsMixin,
    ProjectsMixin,
    GraphMixin,
    MediaMixin,
    WorkflowMixin,
    ChatMixin,
    JobsMixin,
    StoreBase,
):
    """SQLite persistence; every method returns contract models."""


__all__ = ["PURGE_AFTER", "WORKFLOW_HANDLE", "Store", "now"]
