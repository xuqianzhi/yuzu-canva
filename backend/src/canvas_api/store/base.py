"""Shared pieces of the store: helpers, the connection, row -> model."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from ..contract import (
    Asset,
    Edge,
    ErrorCode,
    Job,
    JobInput,
    JobStatus,
    Node,
    NodeParams,
    Output,
    Position,
    Project,
    Size,
    Viewport,
    WorkflowDefinition,
)
from ..domain.workflow import (
    builtin_workflow,
)
from ..errors import ApiError
from .schema import SCHEMA

_PARAMS = TypeAdapter(NodeParams)


ACTIVE = (JobStatus.queued.value, JobStatus.running.value)


LIVE_N = "n.deleted_at IS NULL"


LIVE_ASSETS = (
    "assets a JOIN outputs o ON o.asset_id = a.id "
    "JOIN nodes n ON n.id = o.node_id AND n.deleted_at IS NULL "
    "WHERE a.project_id = p.id"
)


PURGE_AFTER = timedelta(days=1)


WORKFLOW_HANDLE = "workflow"


def now() -> datetime:
    return datetime.now(UTC)


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _not_found(what: str, id_: str) -> ApiError:
    return ApiError(404, ErrorCode.not_found, f"{what} {id_} not found", {"id": id_})


def _workflow_of(stored: str) -> WorkflowDefinition:
    """A project's copy of its workflow; the built-in one if it can't be read."""
    try:
        return WorkflowDefinition.model_validate_json(stored)
    except ValueError:
        return builtin_workflow()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class StoreBase:
    """The connection, transactions, and turning rows into contract models.

    The other parts of the store are mixins on top of this (see __init__.py)."""

    def __init__(self, db_path: Path, assets_dir: Path, global_dir: Path | None = None) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir = assets_dir
        # Files of global assets (not tied to any project).
        self.global_dir = global_dir or assets_dir.parent / "global"
        self.global_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._migrate()
        self._seed_templates()
        with self._tx() as db:
            db.execute(
                "UPDATE projects SET workflow = ? WHERE workflow = ''",
                (self._template_for_project(db, None),),
            )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _one(self, sql: str, *args: Any) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, args).fetchone()

    def _all(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    @staticmethod
    def _project(r: sqlite3.Row) -> Project:
        return Project(
            id=r["id"],
            name=r["name"],
            viewport=Viewport.model_validate_json(r["viewport"]),
            instruction=r["instruction"],
            workflow=_workflow_of(r["workflow"]),
            created_at=_dt(r["created_at"]),
            updated_at=_dt(r["updated_at"]),
        )

    @staticmethod
    def _node(r: sqlite3.Row) -> Node:
        return Node(
            id=r["id"],
            project_id=r["project_id"],
            kind=r["kind"],
            name=r["title"] or None,
            source=r["source"],
            position=Position.model_validate_json(r["position"]),
            size=Size.model_validate_json(r["size"]) if r["size"] else None,
            prompt=r["prompt"],
            params=_PARAMS.validate_json(r["params"]),
            selected_output_id=r["selected_output_id"],
            workflow_step=r["workflow_step"],
            workflow_item=_int_or_none(r["workflow_item"]),
            created_at=_dt(r["created_at"]),
            updated_at=_dt(r["updated_at"]),
        )

    @staticmethod
    def _edge(r: sqlite3.Row) -> Edge:
        workflow = r["target_handle"] == WORKFLOW_HANDLE
        return Edge(
            id=r["id"],
            project_id=r["project_id"],
            source_node_id=r["source_node_id"],
            target_node_id=r["target_node_id"],
            workflow=workflow,
            created_at=_dt(r["created_at"]),
        )

    @staticmethod
    def _asset(r: sqlite3.Row) -> Asset:
        return Asset(
            id=r["id"],
            kind=r["kind"],
            mime=r["mime"],
            url=f"/api/assets/{r['id']}/content",
            bytes=r["bytes"],
            width=r["width"],
            height=r["height"],
            duration_s=r["duration_s"],
            created_at=_dt(r["created_at"]),
        )

    def _output(self, r: sqlite3.Row) -> Output:
        asset = None
        if r["asset_id"]:
            row = self._one("SELECT * FROM assets WHERE id = ?", r["asset_id"])
            asset = self._asset(row) if row else None
        return Output(
            id=r["id"],
            node_id=r["node_id"],
            job_id=r["job_id"],
            kind=r["kind"],
            text=r["text"],
            asset=asset,
            created_at=_dt(r["created_at"]),
        )

    @staticmethod
    def _job(r: sqlite3.Row) -> Job:
        return Job(
            id=r["id"],
            project_id=r["project_id"],
            node_id=r["node_id"],
            status=r["status"],
            provider=r["provider"],
            operation=r["operation"],
            input=JobInput.model_validate_json(r["input"]),
            progress=r["progress"],
            error=r["error"],
            output_id=r["output_id"],
            provider_task_id=r["provider_task_id"],
            created_at=_dt(r["created_at"]),
            started_at=_dt(r["started_at"]),
            finished_at=_dt(r["finished_at"]),
        )

    def _touch_project(self, db: sqlite3.Connection, project_id: str) -> None:
        db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (_ts(now()), project_id))
