"""Bring the database up to the current schema (see schema.MIGRATIONS)."""

from __future__ import annotations

from .schema import MIGRATIONS, TABLES

# Only one API instance migrates at a time (an arbitrary, fixed lock number).
_LOCK = 4_242_001


class MigrationsMixin:
    def _migrate(self) -> None:
        with self._tx() as db:
            db.execute("SELECT pg_advisory_xact_lock(?)", (_LOCK,))
            db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = db.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                db.execute("INSERT INTO schema_version (version) VALUES (0)")
                version = 0
            else:
                version = row["version"]
            for number, sql in enumerate(MIGRATIONS, start=1):
                if number <= version:
                    continue
                db.raw(sql)
                db.execute("UPDATE schema_version SET version = ?", (number,))
            for table in [*TABLES, "schema_version"]:
                db.raw(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
