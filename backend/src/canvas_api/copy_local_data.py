"""Copy what the old local (SQLite) app kept into a new collection of one
user's in the new database: global assets (with their files) become the
collection's assets, the global instruction its instruction, and workflow
templates its workflows (the old default one active); the language goes to
the user. Projects are not copied (copy them by hand if you ever need one).

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
Each run makes a new collection (--name, default "Imported").
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from .files import FileMissing, LocalFiles, make_files
from .ids import new_id
from .store.base import _ts, now
from .store.media import collection_key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True, help="the account to copy into")
    parser.add_argument("--data-dir", default=os.environ.get("CANVAS_DATA_DIR", "./data"))
    parser.add_argument("--bucket", default="", help="target bucket ('' = local files)")
    parser.add_argument("--name", default="Imported", help="the new collection's name")
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
    settings = dict(old.execute("SELECT key, value FROM settings").fetchall())
    ts = _ts(now())

    with psycopg.connect(target, row_factory=dict_row) as db:
        user = db.execute(
            "SELECT id FROM users WHERE lower(email) = lower(%s)", (args.email,)
        ).fetchone()
        if user is None:
            print(f"{args.email} has no account yet: sign in to the app once first.")
            return 1
        owner = user["id"]
        mode = "dry run" if args.dry_run else "for real"
        print(f"Copying into a new collection “{args.name}” of {args.email} ({mode}):")
        collection_id = new_id("col")

        # Workflows: every old template (the old default becomes active).
        workflows = []
        for row in old.execute("SELECT * FROM workflow_templates ORDER BY created_at, id"):
            workflow_id = new_id("wfl")
            definition = json.loads(row["definition"])
            definition.update(id=workflow_id, version=1)
            workflows.append((workflow_id, row["id"], json.dumps(definition)))
            print(f"  workflow {definition.get('name', row['id'])}")
        if not workflows:
            print("No workflow templates in the local database.", file=sys.stderr)
            return 2
        default = settings.get("default_workflow")
        active = next((w for w, old_id, _ in workflows if old_id == default), workflows[0][0])

        instruction = settings.get("instruction") or ""
        print(f"  instruction: {len(instruction)} characters")
        if not args.dry_run:
            db.execute(
                "INSERT INTO collections (id, owner_id, name, instruction, active_workflow_id, "
                "version, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, 1, %s, %s)",
                (collection_id, owner, args.name, instruction, active, ts, ts),
            )
            db.execute(
                "INSERT INTO collection_members (collection_id, user_id, role, created_at) "
                "VALUES (%s, %s, 'owner', %s)",
                (collection_id, owner, ts),
            )
            for workflow_id, _, definition in workflows:
                db.execute(
                    "INSERT INTO collection_workflows (id, collection_id, definition, "
                    "created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
                    (workflow_id, collection_id, definition, ts, ts),
                )

        # Global assets -> the collection's assets: rows and files, new IDs.
        for row in old.execute("SELECT * FROM global_assets ORDER BY created_at, id"):
            try:
                data = source_files.read(f"global/{row['filename']}")
            except FileMissing:
                print(f"  asset {row['name']}: file missing, skipped")
                continue
            new = new_id("cas")
            filename = f"{new}{Path(row['filename']).suffix}"
            print(f"  asset {row['name']} ({len(data) // 1024} KB)")
            if args.dry_run:
                continue
            files.write(collection_key(filename), data, row["mime"])
            db.execute(
                "INSERT INTO collection_assets (id, collection_id, name, kind, mime, filename, "
                "bytes, width, height, duration_s, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    new,
                    collection_id,
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

        # The language, unless already set.
        language = settings.get("language")
        if language and not args.dry_run:
            db.execute(
                "INSERT INTO user_settings (user_id, key, value) VALUES (%s, 'language', %s) "
                "ON CONFLICT (user_id, key) DO NOTHING",
                (owner, language),
            )
        if args.dry_run:
            db.rollback()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
