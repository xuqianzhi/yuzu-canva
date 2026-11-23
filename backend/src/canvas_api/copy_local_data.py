"""Copy what the old local (SQLite) app kept into one user's account in the
new database: global assets (with their files), the global instruction, the
language, and custom workflow templates. Projects are not copied (copy them
by hand if you ever need one).

The user must have signed in to the deployed app once (that creates their
account). Run it in the API image, which has the dependencies, with the
local data mounted (docker compose does) and Google credentials for the
bucket:

    gcloud auth application-default login
    cd backend
    docker compose run --rm -T \\
      -v "$HOME/.config/gcloud:/home/app/.config/gcloud:ro" \\
      -e TARGET_DATABASE_URL -e GOOGLE_CLOUD_PROJECT=yuzu-canva \\
      api python -m canvas_api.copy_local_data --email you@example.com \\
        --bucket yuzu-canva.firebasestorage.app

with TARGET_DATABASE_URL set in your shell to the Supabase string (the same
as DATABASE_URL in backend/.env). Add --dry-run to only see what it would do.
Running it twice is safe: what's already there is skipped.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from .files import FileMissing, LocalFiles, make_files
from .ids import new_id
from .store.base import _ts, now
from .store.media import global_key

BUILTIN_TEMPLATE = "wft_builtin"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True, help="the account to copy into")
    parser.add_argument("--data-dir", default=os.environ.get("CANVAS_DATA_DIR", "./data"))
    parser.add_argument("--bucket", default="", help="target bucket ('' = local files)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    target = os.environ.get("TARGET_DATABASE_URL", "")
    if not target:
        print("Set TARGET_DATABASE_URL to the database to copy into.", file=sys.stderr)
        return 2
    data_dir = Path(args.data_dir)
    source_db = data_dir / "canvas.db"
    if not source_db.is_file():
        print(f"No local database at {source_db}.", file=sys.stderr)
        return 2

    import psycopg
    from psycopg.rows import dict_row

    old = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    old.row_factory = sqlite3.Row
    source_files = LocalFiles(data_dir)
    files = make_files("gcs" if args.bucket else "local", args.bucket, data_dir)

    with psycopg.connect(target, row_factory=dict_row) as db:
        user = db.execute(
            "SELECT id FROM users WHERE lower(email) = lower(%s)", (args.email,)
        ).fetchone()
        if user is None:
            print(f"{args.email} has no account yet: sign in to the app once first.")
            return 1
        owner = user["id"]
        print(f"Copying into {args.email} ({'dry run' if args.dry_run else 'for real'}):")

        # Global assets: rows and files, under new IDs (skipped if the name is taken).
        taken = {
            r["name"].lower()
            for r in db.execute(
                "SELECT name FROM global_assets WHERE owner_id = %s", (owner,)
            ).fetchall()
        }
        for row in old.execute("SELECT * FROM global_assets ORDER BY created_at, id"):
            if row["name"].lower() in taken:
                print(f"  global asset {row['name']}: already there, skipped")
                continue
            key = global_key(row["filename"])
            try:
                data = source_files.read(key)
            except FileMissing:
                print(f"  global asset {row['name']}: file missing, skipped")
                continue
            new = new_id("gas")
            filename = f"{new}{Path(row['filename']).suffix}"
            print(f"  global asset {row['name']} ({len(data) // 1024} KB)")
            if args.dry_run:
                continue
            files.write(global_key(filename), data, row["mime"])
            db.execute(
                "INSERT INTO global_assets (id, owner_id, name, kind, mime, filename, bytes, "
                "width, height, duration_s, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    new,
                    owner,
                    row["name"],
                    row["kind"],
                    row["mime"],
                    filename,
                    len(data),
                    row["width"],
                    row["height"],
                    row["duration_s"],
                    row["created_at"],
                ),
            )

        # Settings: the instruction and language, unless already set there.
        settings = dict(old.execute("SELECT key, value FROM settings").fetchall())
        for key in ("instruction", "language"):
            value = settings.get(key)
            if not value:
                continue
            if db.execute(
                "SELECT 1 FROM user_settings WHERE user_id = %s AND key = %s AND value <> ''",
                (owner, key),
            ).fetchone():
                print(f"  {key}: already set there, kept")
                continue
            print(f"  {key}: {len(value)} characters")
            if not args.dry_run:
                db.execute(
                    "INSERT INTO user_settings (user_id, key, value) VALUES (%s, %s, %s) "
                    "ON CONFLICT (user_id, key) DO UPDATE SET value = excluded.value",
                    (owner, key, value),
                )

        # Custom workflow templates (the built-in one every account has).
        ts = _ts(now())
        for row in old.execute("SELECT * FROM workflow_templates ORDER BY created_at, id"):
            if row["id"] == BUILTIN_TEMPLATE:
                continue
            if db.execute(
                "SELECT 1 FROM workflow_templates WHERE id = %s", (row["id"],)
            ).fetchone():
                print(f"  template {row['id']}: already there, skipped")
                continue
            print(f"  template {row['id']}")
            if not args.dry_run:
                db.execute(
                    "INSERT INTO workflow_templates (id, owner_id, definition, created_at, "
                    "updated_at) VALUES (%s, %s, %s, %s, %s)",
                    (row["id"], owner, row["definition"], row["created_at"], ts),
                )
        if args.dry_run:
            db.rollback()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
