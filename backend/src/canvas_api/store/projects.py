"""Projects, the global instruction and the app's language."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..contract import (
    GLOBAL_NODE_STEP,
    GLOBAL_NODE_X,
    GLOBAL_NODE_Y,
    Language,
    MediaKind,
    Position,
    Project,
    ProjectCreate,
    ProjectGraph,
    ProjectSummary,
    ProjectUpdate,
    Viewport,
)
from ..ids import new_id
from .base import (
    ACTIVE,
    LIVE_ASSETS,
    LIVE_N,
    _not_found,
    _ts,
    now,
)


class ProjectsMixin:
    """Projects, the global instruction and the app's language."""

    def list_projects(self) -> list[Project]:
        rows = self._all("SELECT * FROM projects ORDER BY updated_at DESC, id")
        return [self._project(r) for r in rows]

    def list_project_summaries(self) -> list[ProjectSummary]:
        rows = self._all(
            f"""
            SELECT p.*,
              (SELECT COUNT(*) FROM nodes n WHERE n.project_id = p.id AND {LIVE_N})
                AS node_count,
              (SELECT COUNT(*) FROM {LIVE_ASSETS} AND a.kind = 'image') AS image_count,
              (SELECT COUNT(*) FROM {LIVE_ASSETS} AND a.kind = 'video') AS video_count,
              (SELECT COUNT(*) FROM jobs j WHERE j.project_id = p.id AND j.status IN {ACTIVE})
                AS running_count,
              (SELECT a.id FROM {LIVE_ASSETS} AND a.kind IN ('image', 'video')
                 ORDER BY a.created_at DESC, a.id DESC LIMIT 1) AS cover_id
            FROM projects p ORDER BY p.updated_at DESC, p.id
            """
        )
        summaries = []
        for r in rows:
            cover = self._one("SELECT * FROM assets WHERE id = ?", r["cover_id"])
            summaries.append(
                ProjectSummary(
                    **self._project(r).model_dump(),
                    node_count=r["node_count"],
                    image_count=r["image_count"],
                    video_count=r["video_count"],
                    running_count=r["running_count"],
                    cover=self._asset(cover) if cover else None,
                )
            )
        return summaries

    def get_project(self, project_id: str) -> Project:
        row = self._one("SELECT * FROM projects WHERE id = ?", project_id)
        if not row:
            raise _not_found("project", project_id)
        return self._project(row)

    def create_project(self, body: ProjectCreate) -> Project:
        """Create a project; every global asset becomes an uploaded node in it.

        The nodes go down the left side of the canvas, oldest asset first,
        each named after its asset and holding its own copy of the file.
        """
        project_id, ts = new_id("prj"), _ts(now())
        written: list[Path] = []
        try:
            with self._tx() as db:
                instruction = body.instruction
                if instruction is None:
                    instruction = self._global_instruction(db)
                db.execute(
                    "INSERT INTO projects (id, name, viewport, created_at, updated_at,"
                    " instruction, workflow) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        project_id,
                        body.name,
                        Viewport().model_dump_json(),
                        ts,
                        ts,
                        instruction,
                        self._template_for_project(db, body.workflow_template_id),
                    ),
                )
                rows = db.execute(
                    "SELECT * FROM global_assets ORDER BY created_at, id"
                ).fetchall()
                for i, row in enumerate(rows):
                    source = self.global_dir / row["filename"]
                    _, path = self._insert_upload_node(
                        db,
                        project_id,
                        MediaKind(row["kind"]),
                        source.read_bytes(),
                        row["mime"],
                        source.suffix.lstrip(".") or "bin",
                        row["width"],
                        row["height"],
                        row["duration_s"],
                        name=row["name"],
                        position=Position(
                            x=GLOBAL_NODE_X, y=GLOBAL_NODE_Y + i * GLOBAL_NODE_STEP
                        ),
                    )
                    written.append(path)
        except BaseException:
            for path in written:
                path.unlink(missing_ok=True)
            raise
        return self.get_project(project_id)

    def update_project(self, project_id: str, body: ProjectUpdate) -> Project:
        project = self.get_project(project_id)
        name = body.name if body.name is not None else project.name
        viewport = body.viewport or project.viewport
        instruction = body.instruction if body.instruction is not None else project.instruction
        with self._tx() as db:
            db.execute(
                "UPDATE projects SET name = ?, viewport = ?, instruction = ?, updated_at = ?"
                " WHERE id = ?",
                (name, viewport.model_dump_json(), instruction, _ts(now()), project_id),
            )
        return self.get_project(project_id)

    @staticmethod
    def _global_instruction(db: sqlite3.Connection) -> str:
        row = db.execute("SELECT value FROM settings WHERE key = 'instruction'").fetchone()
        return row["value"] if row else ""

    def get_global_instruction(self) -> str:
        with self._lock:
            return self._global_instruction(self._db)

    def get_language(self) -> Language:
        row = self._one("SELECT value FROM settings WHERE key = 'language'")
        try:
            return Language(row["value"]) if row else Language.en
        except ValueError:
            return Language.en

    def set_language(self, language: Language) -> Language:
        with self._tx() as db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES ('language', ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (language.value,),
            )
        return language

    def set_global_instruction(self, text: str) -> str:
        with self._tx() as db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES ('instruction', ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (text,),
            )
        return text

    def delete_project(self, project_id: str) -> tuple[list[Path], list[str]]:
        """Delete everything in the project.

        Returns (asset files to remove, ids of jobs that were active).
        """
        self.get_project(project_id)
        with self._tx() as db:
            files = [
                self.assets_dir / r["filename"]
                for r in db.execute(
                    "SELECT filename FROM assets WHERE project_id = ?", (project_id,)
                )
            ]
            active = [
                r["id"]
                for r in db.execute(
                    f"SELECT id FROM jobs WHERE project_id = ? AND status IN {ACTIVE}",
                    (project_id,),
                )
            ]
            db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return files, active

    def get_graph(self, project_id: str) -> ProjectGraph:
        project = self.get_project(project_id)
        nodes = self._all(
            "SELECT * FROM nodes WHERE project_id = ? AND deleted_at IS NULL "
            "ORDER BY created_at, id",
            project_id,
        )
        edges = self._all(
            "SELECT * FROM edges WHERE project_id = ? AND deleted_at IS NULL "
            "ORDER BY created_at, id",
            project_id,
        )
        outputs = self._all(
            "SELECT o.* FROM outputs o JOIN nodes n ON n.id = o.node_id "
            "WHERE n.project_id = ? AND n.deleted_at IS NULL ORDER BY o.node_id, o.seq DESC",
            project_id,
        )
        jobs = self._all(
            f"SELECT * FROM jobs WHERE project_id = ? AND status IN {ACTIVE} "
            "ORDER BY created_at",
            project_id,
        )
        return ProjectGraph(
            project=project,
            nodes=[self._node(r) for r in nodes],
            edges=[self._edge(r) for r in edges],
            outputs=[self._output(r) for r in outputs],
            active_jobs=[self._job(r) for r in jobs],
            runs=self.list_runs(project_id),
        )
