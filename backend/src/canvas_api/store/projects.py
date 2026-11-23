"""Projects, and each user's global instruction and language."""

from __future__ import annotations

from pathlib import PurePath

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
from ..files import delete_all
from ..ids import new_id
from .base import (
    ACTIVE,
    LIVE_ASSETS,
    LIVE_N,
    _not_found,
    _ts,
    now,
)
from .media import asset_key, global_key


class ProjectsMixin:
    """Projects, and each user's global instruction and language."""

    def list_projects(self, owner: str) -> list[Project]:
        rows = self._all(
            "SELECT * FROM projects WHERE owner_id = ? ORDER BY updated_at DESC, id", owner
        )
        return [self._project(r) for r in rows]

    def list_project_summaries(self, owner: str) -> list[ProjectSummary]:
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
            FROM projects p WHERE p.owner_id = ? ORDER BY p.updated_at DESC, p.id
            """,
            owner,
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

    def create_project(self, owner: str, body: ProjectCreate) -> Project:
        """Create a project; every global asset becomes an uploaded node in it.

        The nodes go down the left side of the canvas, oldest asset first,
        each named after its asset and holding its own copy of the file.
        """
        project_id, ts = new_id("prj"), _ts(now())
        written: list[str] = []
        try:
            with self._tx() as db:
                instruction = body.instruction
                if instruction is None:
                    instruction = self._setting(db, owner, "instruction") or ""
                db.execute(
                    "INSERT INTO projects (id, owner_id, name, viewport, created_at,"
                    " updated_at, instruction, workflow) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        project_id,
                        owner,
                        body.name,
                        Viewport().model_dump_json(),
                        ts,
                        ts,
                        instruction,
                        self._template_for_project(db, owner, body.workflow_template_id),
                    ),
                )
                rows = db.execute(
                    "SELECT * FROM global_assets WHERE owner_id = ? ORDER BY created_at, id",
                    (owner,),
                ).fetchall()
                for i, row in enumerate(rows):
                    _, key = self._insert_upload_node(
                        db,
                        project_id,
                        MediaKind(row["kind"]),
                        row["mime"],
                        PurePath(row["filename"]).suffix.lstrip(".") or "bin",
                        row["bytes"],
                        row["width"],
                        row["height"],
                        row["duration_s"],
                        name=row["name"],
                        position=Position(
                            x=GLOBAL_NODE_X, y=GLOBAL_NODE_Y + i * GLOBAL_NODE_STEP
                        ),
                        copy_from=global_key(row["filename"]),
                    )
                    written.append(key)
        except BaseException:
            delete_all(self.files, written)
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

    def get_global_instruction(self, owner: str) -> str:
        with self._conn() as db:
            return self._setting(db, owner, "instruction") or ""

    def get_language(self, owner: str) -> Language:
        with self._conn() as db:
            value = self._setting(db, owner, "language")
        try:
            return Language(value) if value else Language.en
        except ValueError:
            return Language.en

    def set_language(self, owner: str, language: Language) -> Language:
        with self._tx() as db:
            self._put_setting(db, owner, "language", language.value)
        return language

    def set_global_instruction(self, owner: str, text: str) -> str:
        with self._tx() as db:
            self._put_setting(db, owner, "instruction", text)
        return text

    def delete_project(self, project_id: str) -> tuple[list[str], list[str]]:
        """Delete everything in the project.

        Returns (asset files to remove, ids of jobs that were active).
        """
        self.get_project(project_id)
        with self._tx() as db:
            files = [
                asset_key(r["filename"])
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
