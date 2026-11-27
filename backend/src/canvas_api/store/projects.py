"""Projects, and each user's language."""

from __future__ import annotations

from pathlib import PurePath

from ..contract import (
    ASSET_NODE_STEP,
    ASSET_NODE_X,
    ASSET_NODE_Y,
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
    PROJECT_SQL,
    _not_found,
    _ts,
    now,
)
from .media import asset_key, collection_key


class ProjectsMixin:
    """Projects, and each user's language."""

    def list_project_summaries(self, collection_id: str, user_id: str) -> list[ProjectSummary]:
        """The collection's projects, most recently updated first."""
        rows = self._all(
            f"""
            SELECT p.*, w.definition AS workflow, c.instruction AS collection_instruction,
              (SELECT COUNT(*) FROM nodes n WHERE n.project_id = p.id AND {LIVE_N})
                AS node_count,
              (SELECT COUNT(*) FROM {LIVE_ASSETS} AND a.kind = 'image') AS image_count,
              (SELECT COUNT(*) FROM {LIVE_ASSETS} AND a.kind = 'video') AS video_count,
              (SELECT COUNT(*) FROM jobs j WHERE j.project_id = p.id AND j.status IN {ACTIVE})
                AS running_count,
              (SELECT a.id FROM {LIVE_ASSETS} AND a.kind IN ('image', 'video')
                 ORDER BY a.created_at DESC, a.id DESC LIMIT 1) AS cover_id
            FROM projects p JOIN collections c ON c.id = p.collection_id
            JOIN collection_workflows w ON w.id = c.active_workflow_id
            WHERE p.collection_id = ? ORDER BY p.updated_at DESC, p.id
            """,
            collection_id,
        )
        editing = self.editing_now(collection_id)
        summaries = []
        for r in rows:
            cover = self._one("SELECT * FROM assets WHERE id = ?", r["cover_id"])
            holder = editing.get(r["id"])
            summaries.append(
                ProjectSummary(
                    **self._project(r).model_dump(),
                    node_count=r["node_count"],
                    image_count=r["image_count"],
                    video_count=r["video_count"],
                    running_count=r["running_count"],
                    cover=self._asset(cover) if cover else None,
                    editing_by=holder[1] if holder and holder[0] != user_id else None,
                )
            )
        return summaries

    def get_project(self, project_id: str) -> Project:
        row = self._one(PROJECT_SQL + "WHERE p.id = ?", project_id)
        if not row:
            raise _not_found("project", project_id)
        return self._project(row)

    def create_project(self, collection_id: str, body: ProjectCreate) -> Project:
        """Create a project in a collection; every collection asset becomes an
        uploaded node in it.

        The nodes go down the left side of the canvas, oldest asset first,
        each named after its asset and holding its own copy of the file.
        """
        project_id, ts = new_id("prj"), _ts(now())
        written: list[str] = []
        try:
            with self._tx() as db:
                collection = db.execute(
                    "SELECT 1 FROM collections WHERE id = ?", (collection_id,)
                ).fetchone()
                if collection is None:
                    raise _not_found("collection", collection_id)
                description = body.description or ""
                db.execute(
                    "INSERT INTO projects (id, collection_id, name, viewport, created_at,"
                    " updated_at, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        project_id,
                        collection_id,
                        body.name,
                        Viewport().model_dump_json(),
                        ts,
                        ts,
                        description,
                    ),
                )
                rows = db.execute(
                    "SELECT * FROM collection_assets WHERE collection_id = ? "
                    "ORDER BY created_at, id",
                    (collection_id,),
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
                        position=Position(x=ASSET_NODE_X, y=ASSET_NODE_Y + i * ASSET_NODE_STEP),
                        copy_from=collection_key(row["filename"]),
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
        description = body.description if body.description is not None else project.description
        with self._tx() as db:
            db.execute(
                "UPDATE projects SET name = ?, viewport = ?, description = ?, updated_at = ?"
                " WHERE id = ?",
                (name, viewport.model_dump_json(), description, _ts(now()), project_id),
            )
        return self.get_project(project_id)

    def get_language(self, user_id: str) -> Language:
        with self._conn() as db:
            value = self._setting(db, user_id, "language")
        try:
            return Language(value) if value else Language.en
        except ValueError:
            return Language.en

    def set_language(self, user_id: str, language: Language) -> Language:
        with self._tx() as db:
            self._put_setting(db, user_id, "language", language.value)
        return language

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
        with self._snapshot():
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
                "WHERE n.project_id = ? AND n.deleted_at IS NULL "
                "ORDER BY o.node_id, o.seq DESC",
                project_id,
            )
            jobs = self._all(
                f"SELECT * FROM jobs WHERE project_id = ? AND status IN {ACTIVE} "
                "ORDER BY created_at",
                project_id,
            )
            # Nodes of steps the active workflow doesn't have are hidden (not
            # deleted): switching back to a workflow with them shows them again.
            steps = {step.key for step in project.workflow.steps}
            shown = {
                r["id"]
                for r in nodes
                if r["workflow_step"] is None or r["workflow_step"] in steps
            }
            return ProjectGraph(
                project=project,
                nodes=[self._node(r) for r in nodes if r["id"] in shown],
                edges=[
                    self._edge(r)
                    for r in edges
                    if r["source_node_id"] in shown and r["target_node_id"] in shown
                ],
                outputs=[self._output(r) for r in outputs if r["node_id"] in shown],
                active_jobs=[self._job(r) for r in jobs if r["node_id"] in shown],
                runs=[run for run in self.list_runs(project_id) if run.step in steps],
            )
