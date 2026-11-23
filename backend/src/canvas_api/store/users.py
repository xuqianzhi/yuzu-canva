"""Users: who signed in, their settings, what they own, what they spent."""

from __future__ import annotations

from datetime import datetime

from .base import Db, _not_found, _ts, now

# How to find the user who owns a thing, by the kind of thing.
_OWNER_SQL = {
    "project": "SELECT owner_id FROM projects WHERE id = ?",
    "node": "SELECT p.owner_id FROM nodes n JOIN projects p ON p.id = n.project_id "
    "WHERE n.id = ?",
    "edge": "SELECT p.owner_id FROM edges e JOIN projects p ON p.id = e.project_id "
    "WHERE e.id = ?",
    "job": "SELECT p.owner_id FROM jobs j JOIN projects p ON p.id = j.project_id "
    "WHERE j.id = ?",
    "material": "SELECT p.owner_id FROM materials m JOIN projects p ON p.id = m.project_id "
    "WHERE m.id = ?",
    "message": "SELECT p.owner_id FROM messages m JOIN nodes n ON n.id = m.node_id "
    "JOIN projects p ON p.id = n.project_id WHERE m.id = ?",
    "output": "SELECT p.owner_id FROM outputs o JOIN nodes n ON n.id = o.node_id "
    "JOIN projects p ON p.id = n.project_id WHERE o.id = ?",
    "template": "SELECT owner_id FROM workflow_templates WHERE id = ?",
    "global_asset": "SELECT owner_id FROM global_assets WHERE id = ?",
}


class UsersMixin:
    def ensure_user(self, user_id: str, email: str) -> bool:
        """Record a sign-in. A new user gets the built-in workflow as their
        first template. Returns whether the user is new."""
        ts = _ts(now())
        with self._tx() as db:
            row = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO users (id, email, created_at, last_seen_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, email, ts, ts),
                )
            else:
                db.execute(
                    "UPDATE users SET email = ?, last_seen_at = ? WHERE id = ?",
                    (email, ts, user_id),
                )
            self._seed_templates(db, user_id)
        return row is None

    def owner_of(self, kind: str, id_: str) -> str:
        """The user who owns it (404 if it doesn't exist)."""
        row = self._one(_OWNER_SQL[kind], id_)
        if row is None:
            raise _not_found(kind.replace("_", " "), id_)
        return row["owner_id"]

    @staticmethod
    def _setting(db: Db, owner: str, key: str) -> str | None:
        row = db.execute(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (owner, key)
        ).fetchone()
        return row["value"] if row else None

    @staticmethod
    def _put_setting(db: Db, owner: str, key: str, value: str) -> None:
        db.execute(
            "INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, key) DO UPDATE SET value = excluded.value",
            (owner, key, value),
        )

    # --- spending -------------------------------------------------------------------

    def record_usage(self, owner: str, kind: str, amount: int = 1) -> None:
        with self._tx() as db:
            db.execute(
                "INSERT INTO usage (user_id, kind, amount, created_at) VALUES (?, ?, ?, ?)",
                (owner, kind, amount, _ts(now())),
            )

    def usage_since(self, owner: str, since: datetime) -> dict[str, int]:
        """What the user used since `since`, by kind."""
        rows = self._all(
            "SELECT kind, SUM(amount) AS total FROM usage "
            "WHERE user_id = ? AND created_at >= ? GROUP BY kind",
            owner,
            _ts(since),
        )
        return {r["kind"]: int(r["total"]) for r in rows}

    def active_job_count(self, owner: str) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM jobs j JOIN projects p ON p.id = j.project_id "
            "WHERE p.owner_id = ? AND j.status IN ('queued', 'running')",
            owner,
        )
        return int(row["n"]) if row else 0
