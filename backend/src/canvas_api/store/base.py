"""Shared pieces of the store: helpers, the connection, row -> model."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from psycopg import Connection, Cursor
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
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
from ..files import Files, UrlSigner

_PARAMS = TypeAdapter(NodeParams)


ACTIVE = (JobStatus.queued.value, JobStatus.running.value)


LIVE_N = "n.deleted_at IS NULL"


LIVE_ASSETS = (
    "assets a JOIN outputs o ON o.asset_id = a.id "
    "JOIN nodes n ON n.id = o.node_id AND n.deleted_at IS NULL "
    "WHERE a.project_id = p.id"
)


PURGE_AFTER = timedelta(days=1)


# A project row as `_project` reads it: with its collection's active
# workflow as `workflow`. Add "WHERE ..." (projects are `p`).
PROJECT_SQL = (
    "SELECT p.*, w.definition AS workflow, c.instruction AS collection_instruction, "
    "c.direct_image, c.direct_video "
    "FROM projects p "
    "JOIN collections c ON c.id = p.collection_id "
    "JOIN collection_workflows w ON w.id = c.active_workflow_id "
)


WORKFLOW_HANDLE = "workflow"

Row = dict[str, Any]


def now() -> datetime:
    return datetime.now(UTC)


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _not_found(what: str, id_: str) -> ApiError:
    return ApiError(404, ErrorCode.not_found, f"{what} {id_} not found", {"id": id_})


def _workflow_of(stored: str) -> WorkflowDefinition:
    """A stored workflow; the built-in one if it can't be read."""
    try:
        return WorkflowDefinition.model_validate_json(stored)
    except ValueError:
        return builtin_workflow()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


_QUOTED = re.compile(r"('(?:[^']|'')*')")


@lru_cache(maxsize=1024)
def _pg(sql: str) -> str:
    """The store writes `?` placeholders; psycopg wants `%s` (and `%%` for a
    literal percent sign). Quoted strings are left alone."""
    parts = _QUOTED.split(sql)
    for i in range(0, len(parts), 2):  # outside quotes
        parts[i] = parts[i].replace("%", "%%").replace("?", "%s")
    for i in range(1, len(parts), 2):  # inside quotes
        parts[i] = parts[i].replace("%", "%%")
    return "".join(parts)


class Db:
    """One connection, as the store's code uses it: `execute(sql, params)`
    with `?` placeholders, rows as dicts."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple | list = ()) -> Cursor:
        return self._conn.execute(_pg(sql), tuple(params))

    def raw(self, sql: str) -> None:
        """Run SQL as it is (several statements, no parameters)."""
        self._conn.execute(sql.encode())


class StoreBase:
    """The connection pool, transactions, and turning rows into contract
    models.

    The other parts of the store are mixins on top of this (see __init__.py).
    Writes run one at a time (one lock), as they did on SQLite: the API runs
    as a single instance, and it keeps read-then-write logic simple.
    """

    def __init__(
        self,
        database_url: str,
        files: Files,
        signer: UrlSigner | None = None,
        *,
        pool_size: int = 4,
    ) -> None:
        self.files = files
        self.signer = signer or UrlSigner("")
        self._lock = threading.RLock()
        self._local = threading.local()
        self._pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=pool_size,
            kwargs={"row_factory": dict_row, "autocommit": True, "prepare_threshold": None},
            # Connections dropped by the network or the pooler are replaced.
            check=ConnectionPool.check_connection,
            open=True,
        )
        self._migrate()

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def _conn(self) -> Iterator[Db]:
        current = getattr(self._local, "db", None)
        if current is not None:  # inside _tx(): see its uncommitted writes
            yield current
            return
        with self._pool.connection() as conn:
            yield Db(conn)

    @contextmanager
    def _tx(self) -> Iterator[Db]:
        with self._lock:
            if getattr(self._local, "db", None) is not None:
                raise RuntimeError("nested transaction")
            with self._pool.connection() as conn, conn.transaction():
                db = Db(conn)
                self._local.db = db
                try:
                    yield db
                finally:
                    self._local.db = None

    @contextmanager
    def _snapshot(self) -> Iterator[Db]:
        """Reads that all see one moment of the database: nothing written
        between them shows in only some (a finished run with its nodes
        missing). Needs no lock and blocks no writer. Inside _tx() or
        another snapshot, it is that one."""
        current = getattr(self._local, "db", None)
        if current is not None:
            yield current
            return
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            db = Db(conn)
            self._local.db = db
            try:
                yield db
            finally:
                self._local.db = None

    def _one(self, sql: str, *args: Any) -> Row | None:
        with self._conn() as db:
            return db.execute(sql, args).fetchone()

    def _all(self, sql: str, *args: Any) -> list[Row]:
        with self._conn() as db:
            return db.execute(sql, args).fetchall()

    @staticmethod
    def _project(r: Row) -> Project:
        return Project(
            id=r["id"],
            collection_id=r["collection_id"],
            name=r["name"],
            viewport=Viewport.model_validate_json(r["viewport"]),
            instruction=r["instruction"],
            collection_instruction=r.get("collection_instruction") or "",
            workflow=_workflow_of(r["workflow"]),
            direct_image=bool(r["direct_image"]),
            direct_video=bool(r["direct_video"]),
            created_at=_dt(r["created_at"]),
            updated_at=_dt(r["updated_at"]),
        )

    @staticmethod
    def _node(r: Row) -> Node:
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
            edited=bool(r.get("edited")),
            created_at=_dt(r["created_at"]),
            updated_at=_dt(r["updated_at"]),
        )

    @staticmethod
    def _edge(r: Row) -> Edge:
        workflow = r["target_handle"] == WORKFLOW_HANDLE
        return Edge(
            id=r["id"],
            project_id=r["project_id"],
            source_node_id=r["source_node_id"],
            target_node_id=r["target_node_id"],
            workflow=workflow,
            created_at=_dt(r["created_at"]),
        )

    def _asset(self, r: Row) -> Asset:
        return Asset(
            id=r["id"],
            kind=r["kind"],
            mime=r["mime"],
            url=self.signer.url("assets", r["id"]),
            bytes=r["bytes"],
            width=r["width"],
            height=r["height"],
            duration_s=r["duration_s"],
            created_at=_dt(r["created_at"]),
        )

    def _output(self, r: Row) -> Output:
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
    def _job(r: Row) -> Job:
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
            provider_seed=r.get("provider_seed"),
            created_at=_dt(r["created_at"]),
            started_at=_dt(r["started_at"]),
            finished_at=_dt(r["finished_at"]),
        )

    def _touch_project(self, db: Db, project_id: str) -> None:
        db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (_ts(now()), project_id))
