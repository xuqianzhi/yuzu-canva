"""Bring databases made by older versions up to the current schema."""

from __future__ import annotations

import json

from ..contract import (
    WorkflowDefinition,
    name_key,
)
from ..domain.mentions import (
    find_mentions,
    is_valid_id,
    to_valid_id,
)
from .base import (
    WORKFLOW_HANDLE,
    _ts,
    now,
)


class MigrationsMixin:
    """Bring databases made by older versions up to the current schema."""

    def _migrate(self) -> None:
        """Bring databases made by older versions up to SCHEMA."""

        def columns(table: str) -> set[str]:
            return {r["name"] for r in self._db.execute(f"PRAGMA table_info({table})")}

        if "instruction" not in columns("projects"):
            self._db.execute(
                "ALTER TABLE projects ADD COLUMN instruction TEXT NOT NULL DEFAULT ''"
            )
        if "provider_task_id" not in columns("jobs"):
            self._db.execute("ALTER TABLE jobs ADD COLUMN provider_task_id TEXT")
        # Soft delete (for undo): deleted rows stay until purge_deleted().
        for table in ("nodes", "edges"):
            if "deleted_at" not in columns(table):
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN deleted_at TEXT")
        for column in ("role", "character"):
            if column not in columns("nodes"):
                self._db.execute(f"ALTER TABLE nodes ADD COLUMN {column} TEXT")
        # Edges name the input they feed (a character trait, or '' for the
        # main input), and one source may feed several traits: the UNIQUE
        # constraint changes, so the table is rebuilt.
        if "target_handle" not in columns("edges"):
            self._db.execute("PRAGMA foreign_keys = OFF")
            self._db.executescript(
                """
                BEGIN;
                ALTER TABLE edges RENAME TO edges_old;
                CREATE TABLE edges (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    target_node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    deleted_at TEXT,
                    target_handle TEXT NOT NULL DEFAULT '',
                    UNIQUE (source_node_id, target_node_id, target_handle)
                );
                INSERT INTO edges (id, project_id, source_node_id, target_node_id,
                                   created_at, deleted_at)
                    SELECT id, project_id, source_node_id, target_node_id,
                           created_at, deleted_at FROM edges_old;
                DROP TABLE edges_old;
                CREATE INDEX IF NOT EXISTS edges_project ON edges(project_id);
                COMMIT;
                """
            )
            self._db.execute("PRAGMA foreign_keys = ON")
        self._migrate_ids()
        self._migrate_mentions()
        self._migrate_characters()
        if "source" not in columns("nodes"):
            self._db.execute(
                "ALTER TABLE nodes ADD COLUMN source TEXT NOT NULL DEFAULT 'generate'"
            )
        # Uploaded nodes' takes have no job: make outputs.job_id nullable.
        # SQLite cannot drop NOT NULL in place, so the table is rebuilt.
        job_id = next(
            r for r in self._db.execute("PRAGMA table_info(outputs)") if r["name"] == "job_id"
        )
        if job_id["notnull"]:
            self._db.execute("PRAGMA foreign_keys = OFF")
            self._db.executescript(
                """
                BEGIN;
                ALTER TABLE outputs RENAME TO outputs_old;
                CREATE TABLE outputs (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    job_id TEXT,
                    kind TEXT NOT NULL,
                    text TEXT,
                    asset_id TEXT REFERENCES assets(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL
                );
                INSERT INTO outputs SELECT * FROM outputs_old;
                DROP TABLE outputs_old;
                CREATE INDEX IF NOT EXISTS outputs_node ON outputs(node_id);
                COMMIT;
                """
            )
            self._db.execute("PRAGMA foreign_keys = ON")
        # Workflows: every project gets its own copy of the built-in one.
        if "workflow" not in columns("projects"):
            self._db.execute(
                "ALTER TABLE projects ADD COLUMN workflow TEXT NOT NULL DEFAULT ''"
            )
        for column, sql_type in (
            ("workflow_step", "TEXT"),
            ("workflow_item", "INTEGER"),
        ):
            if column not in columns("nodes"):
                self._db.execute(f"ALTER TABLE nodes ADD COLUMN {column} {sql_type}")
        self._migrate_workflows()
        # One live node per workflow step (per item, in a per-item step).
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS nodes_workflow ON nodes "
            "(project_id, workflow_step, IFNULL(workflow_item, 0)) "
            "WHERE deleted_at IS NULL AND workflow_step IS NOT NULL"
        )

    def _migrate_mentions(self) -> None:
        """Once (user_version 0 -> 1): IDs are mentioned without "@", and a
        character's description moved into its prompt."""
        if self._db.execute("PRAGMA user_version").fetchone()[0] >= 1:
            return
        if "role" in {r["name"] for r in self._db.execute("PRAGMA table_info(nodes)")}:
            rows = self._db.execute(
                "SELECT id, prompt, character FROM nodes WHERE character IS NOT NULL"
            ).fetchall()
            for r in rows:
                sheet = json.loads(r["character"])
                description = sheet.pop("description", "") or ""
                prompt = r["prompt"] if r["prompt"].strip() else description
                self._db.execute(
                    "UPDATE nodes SET prompt = ?, character = ? WHERE id = ?",
                    (prompt, json.dumps(sheet), r["id"]),
                )
        projects = self._db.execute("SELECT DISTINCT project_id FROM nodes").fetchall()
        for p in projects:
            ids = {
                r["title"]: r["id"]
                for r in self._db.execute(
                    "SELECT id, title FROM nodes WHERE project_id = ? AND title != ''",
                    (p["project_id"],),
                )
            }
            rows = self._db.execute(
                "SELECT id, prompt FROM nodes WHERE project_id = ? AND prompt LIKE '%@%'",
                (p["project_id"],),
            ).fetchall()
            for r in rows:
                prompt, out, last = r["prompt"], [], 0
                for start, end, _ in find_mentions(prompt, ids):
                    cut = start - 1 if start and prompt[start - 1] == "@" else start
                    out.append(prompt[last:cut])
                    out.append(prompt[start:end])
                    last = end
                out.append(prompt[last:])
                cleaned = "".join(out)
                if cleaned != prompt:
                    self._db.execute(
                        "UPDATE nodes SET prompt = ? WHERE id = ?", (cleaned, r["id"])
                    )
        self._db.execute("PRAGMA user_version = 1")

    def _migrate_workflows(self) -> None:
        """Once (user_version 2 -> 4): workflows became templates (steps run
        with a prompt and a count). Nodes of earlier workflow versions become
        plain nodes, templates in an older shape are dropped (the built-in one
        is seeded again), unused tables go, and projects start over with the
        default template."""
        if self._db.execute("PRAGMA user_version").fetchone()[0] >= 4:
            return
        self._db.execute("DROP TABLE IF EXISTS step_plans")
        self._db.execute(
            "UPDATE nodes SET workflow_step = NULL, workflow_item = NULL "
            "WHERE workflow_step IS NOT NULL"
        )
        self._db.execute(
            "UPDATE edges SET deleted_at = ? WHERE target_handle = ? AND deleted_at IS NULL",
            (_ts(now()), WORKFLOW_HANDLE),
        )
        if self._db.execute(
            "SELECT name FROM sqlite_master WHERE name = 'workflow_templates'"
        ).fetchone():
            for row in self._db.execute(
                "SELECT id, definition FROM workflow_templates"
            ).fetchall():
                try:
                    WorkflowDefinition.model_validate_json(row["definition"])
                except ValueError:
                    self._db.execute(
                        "DELETE FROM workflow_templates WHERE id = ?", (row["id"],)
                    )
        self._db.execute("UPDATE projects SET workflow = ''")
        self._db.execute("PRAGMA user_version = 4")

    def _migrate_characters(self) -> None:
        """Once (user_version 1 -> 2): node subtypes are gone. A character
        becomes a plain image node whose prompt keeps everything it had: its
        description, then one line per trait -- the text, or the ID of the
        image that gave it (which the prompt then links, as any mention)."""
        if self._db.execute("PRAGMA user_version").fetchone()[0] >= 2:
            return
        if "role" in {r["name"] for r in self._db.execute("PRAGMA table_info(nodes)")}:
            labels = {
                "style": "Style",
                "color": "Color",
                "body_shape": "Body shape",
                "age": "Age",
            }
            rows = self._db.execute(
                "SELECT id, prompt, character FROM nodes WHERE role IS NOT NULL"
            ).fetchall()
            for r in rows:
                sheet = json.loads(r["character"]) if r["character"] else {}
                images = {
                    e["target_handle"]: e["title"]
                    for e in self._db.execute(
                        "SELECT e.target_handle, s.title FROM edges e JOIN nodes s "
                        "ON s.id = e.source_node_id WHERE e.target_node_id = ? "
                        "AND e.deleted_at IS NULL AND e.target_handle IN "
                        "('style', 'color', 'body_shape', 'age')",
                        (r["id"],),
                    )
                }
                lines = []
                for trait, label in labels.items():
                    value = images.get(trait) or " ".join(str(sheet.get(trait, "")).split())
                    if value:
                        lines.append(f"{label}: {value}")
                prompt = "\n".join([r["prompt"].rstrip(), *lines]).strip()
                self._db.execute(
                    "UPDATE nodes SET prompt = ?, role = NULL, character = NULL WHERE id = ?",
                    (prompt, r["id"]),
                )
                # The trait links become mentions (re-linked on start-up).
                self._db.execute(
                    "UPDATE edges SET deleted_at = ? WHERE target_node_id = ? "
                    "AND target_handle IN ('style', 'color', 'body_shape', 'age')",
                    (_ts(now()), r["id"]),
                )
        self._db.execute("PRAGMA user_version = 2")

    def _migrate_ids(self) -> None:
        """Names became IDs: no spaces or punctuation. Fix older ones."""
        rows = self._db.execute("SELECT id, project_id, title FROM nodes WHERE title != ''")
        taken: dict[str, set[str]] = {}
        fixes = []
        for r in rows.fetchall():
            if is_valid_id(r["title"]):
                taken.setdefault(r["project_id"], set()).add(name_key(r["title"]))
            else:
                fixes.append(r)
        for r in fixes:
            used = taken.setdefault(r["project_id"], set())
            base = candidate = to_valid_id(r["title"])
            n = 1
            while name_key(candidate) in used:
                n += 1
                candidate = f"{base}_{n}"
            used.add(name_key(candidate))
            self._db.execute("UPDATE nodes SET title = ? WHERE id = ?", (candidate, r["id"]))
        if "global_assets" in {
            r["name"] for r in self._db.execute("SELECT name FROM sqlite_master")
        }:
            used = set()
            rows = self._db.execute("SELECT id, name FROM global_assets ORDER BY created_at")
            for r in rows.fetchall():
                base = candidate = (
                    r["name"] if is_valid_id(r["name"]) else to_valid_id(r["name"])
                )
                n = 1
                while name_key(candidate) in used:
                    n += 1
                    candidate = f"{base}_{n}"
                used.add(name_key(candidate))
                if candidate != r["name"]:
                    self._db.execute(
                        "UPDATE global_assets SET name = ? WHERE id = ?", (candidate, r["id"])
                    )
