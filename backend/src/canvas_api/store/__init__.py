"""Postgres persistence. Every method returns contract models.

A small connection pool; writes run one at a time under a lock (routes run
in a thread pool and the job worker on the event loop, and every call here
is short). Media files live in `files` (see files.py).

The store is split by area into mixins; ``Store`` puts them together.
"""

from __future__ import annotations

from .base import PURGE_AFTER, WORKFLOW_HANDLE, StoreBase, now
from .chat import ChatMixin
from .collections import CollectionsMixin
from .graph import GraphMixin
from .jobs import JobsMixin
from .media import MediaMixin
from .migrations import MigrationsMixin
from .projects import ProjectsMixin
from .users import UsersMixin
from .workflow import WorkflowMixin


class Store(
    MigrationsMixin,
    UsersMixin,
    CollectionsMixin,
    ProjectsMixin,
    GraphMixin,
    MediaMixin,
    WorkflowMixin,
    ChatMixin,
    JobsMixin,
    StoreBase,
):
    """Postgres persistence; every method returns contract models."""


__all__ = ["PURGE_AFTER", "WORKFLOW_HANDLE", "Store", "now"]
