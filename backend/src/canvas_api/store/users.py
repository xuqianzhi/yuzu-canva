"""Users: who signed in, their settings, what they can reach, what they spent."""

from __future__ import annotations

from datetime import datetime

from ..contract import Role, UsageCounts, UsageLine
from .base import Db, _not_found, _ts, now

# How to find the collection (and project, if any) a thing belongs to, by
# the kind of thing.
_WHERE_SQL = {
    "collection": "SELECT id AS collection_id, NULL AS project_id FROM collections "
    "WHERE id = ?",
    "project": "SELECT collection_id, id AS project_id FROM projects WHERE id = ?",
    "node": "SELECT p.collection_id, p.id AS project_id FROM nodes n "
    "JOIN projects p ON p.id = n.project_id WHERE n.id = ?",
    "edge": "SELECT p.collection_id, p.id AS project_id FROM edges e "
    "JOIN projects p ON p.id = e.project_id WHERE e.id = ?",
    "job": "SELECT p.collection_id, p.id AS project_id FROM jobs j "
    "JOIN projects p ON p.id = j.project_id WHERE j.id = ?",
    "material": "SELECT p.collection_id, p.id AS project_id FROM materials m "
    "JOIN projects p ON p.id = m.project_id WHERE m.id = ?",
    "message": "SELECT p.collection_id, p.id AS project_id FROM messages m "
    "JOIN nodes n ON n.id = m.node_id JOIN projects p ON p.id = n.project_id WHERE m.id = ?",
    "output": "SELECT p.collection_id, p.id AS project_id FROM outputs o "
    "JOIN nodes n ON n.id = o.node_id JOIN projects p ON p.id = n.project_id WHERE o.id = ?",
    "workflow": "SELECT collection_id, NULL AS project_id FROM collection_workflows "
    "WHERE id = ?",
    "collection_asset": "SELECT collection_id, NULL AS project_id FROM collection_assets "
    "WHERE id = ?",
}


def _counts(by_kind: dict[str, int]) -> UsageCounts:
    return UsageCounts(
        text=by_kind.get("text", 0),
        image=by_kind.get("image", 0),
        video=by_kind.get("video", 0),
    )


class UsersMixin:
    def ensure_user(self, user_id: str, email: str) -> bool:
        """Record a sign-in. Returns whether the user is new."""
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
        return row is None

    def locate(self, kind: str, id_: str) -> tuple[str, str | None]:
        """(collection id, project id or None) of a thing (404 if it doesn't
        exist)."""
        row = self._one(_WHERE_SQL[kind], id_)
        if row is None:
            raise _not_found(kind.replace("_", " "), id_)
        return row["collection_id"], row["project_id"]

    def role_in(self, collection_id: str, user_id: str) -> Role | None:
        """The user's role in the collection (None: not a member)."""
        row = self._one(
            "SELECT role FROM collection_members WHERE collection_id = ? AND user_id = ?",
            collection_id,
            user_id,
        )
        return Role(row["role"]) if row else None

    def collection_of(self, project_id: str) -> str:
        return self.locate("project", project_id)[0]

    def owner_of_collection(self, collection_id: str) -> str:
        row = self._one("SELECT owner_id FROM collections WHERE id = ?", collection_id)
        if row is None:
            raise _not_found("collection", collection_id)
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

    def record_usage(
        self, payer: str, actor: str, collection_id: str, kind: str, amount: int = 1
    ) -> None:
        with self._tx() as db:
            db.execute(
                "INSERT INTO usage (payer_id, actor_id, collection_id, kind, amount, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (payer, actor, collection_id, kind, amount, _ts(now())),
            )

    def usage_since(self, payer: str, since: datetime) -> dict[str, int]:
        """What `payer` pays for since `since` (everyone's use), by kind."""
        rows = self._all(
            "SELECT kind, SUM(amount) AS total FROM usage "
            "WHERE payer_id = ? AND created_at >= ? GROUP BY kind",
            payer,
            _ts(since),
        )
        return {r["kind"]: int(r["total"]) for r in rows}

    def usage_in(self, collection_id: str, actor: str, since: datetime) -> dict[str, int]:
        """What `actor` generated in the collection since `since`, by kind."""
        rows = self._all(
            "SELECT kind, SUM(amount) AS total FROM usage WHERE collection_id = ? "
            "AND actor_id = ? AND created_at >= ? GROUP BY kind",
            collection_id,
            actor,
            _ts(since),
        )
        return {r["kind"]: int(r["total"]) for r in rows}

    def usage_breakdown(self, payer: str, since: datetime) -> list[UsageLine]:
        """What `payer` pays for since `since`, by collection and person."""
        rows = self._all(
            "SELECT u.collection_id, c.name AS collection_name, a.email, u.kind, "
            "SUM(u.amount) AS total FROM usage u "
            "LEFT JOIN collections c ON c.id = u.collection_id "
            "LEFT JOIN users a ON a.id = u.actor_id "
            "WHERE u.payer_id = ? AND u.created_at >= ? "
            "GROUP BY u.collection_id, c.name, a.email, u.kind",
            payer,
            _ts(since),
        )
        lines: dict[tuple, dict[str, int]] = {}
        for r in rows:
            key = (r["collection_id"], r["collection_name"], r["email"])
            lines.setdefault(key, {})[r["kind"]] = int(r["total"])
        result = [
            UsageLine(collection_id=cid, collection_name=name, email=email, used=_counts(used))
            for (cid, name, email), used in lines.items()
        ]
        result.sort(key=lambda line: -sum(line.used.model_dump().values()))
        return result

    def active_job_count(self, payer: str) -> int:
        """Jobs waiting or running in every collection `payer` owns."""
        row = self._one(
            "SELECT COUNT(*) AS n FROM jobs j JOIN projects p ON p.id = j.project_id "
            "JOIN collections c ON c.id = p.collection_id "
            "WHERE c.owner_id = ? AND j.status IN ('queued', 'running')",
            payer,
        )
        return int(row["n"]) if row else 0
