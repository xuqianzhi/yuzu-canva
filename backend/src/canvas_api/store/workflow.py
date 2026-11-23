"""Running a project's workflow steps."""

from __future__ import annotations

from ..contract import (
    ErrorCode,
    JobStatus,
    MediaKind,
    Node,
    NodeSource,
    Output,
    OutputUse,
    Position,
    RunStatus,
    StepRun,
    default_params,
)
from ..domain.mentions import (
    mentioned,
)
from ..domain.workflow import (
    position_for,
    step_by_key,
)
from ..errors import ApiError
from ..ids import new_id
from .base import (
    ACTIVE,
    WORKFLOW_HANDLE,
    Db,
    _dt,
    _not_found,
    _ts,
    now,
)


class WorkflowMixin:
    """Running a project's workflow steps."""

    def list_runs(self, project_id: str) -> list[StepRun]:
        rows = self._all(
            "SELECT * FROM step_runs WHERE project_id = ? ORDER BY step", project_id
        )
        return [
            StepRun(
                step=r["step"],
                prompt=r["prompt"],
                count=r["count"],
                status=r["status"],
                error=r["error"],
                updated_at=_dt(r["updated_at"]),
            )
            for r in rows
        ]

    def start_run(self, project_id: str, key: str, prompt: str, count: int) -> None:
        """Mark a step's run as started (409 if one is already running)."""
        with self._tx() as db:
            row = db.execute(
                "SELECT status FROM step_runs WHERE project_id = ? AND step = ?",
                (project_id, key),
            ).fetchone()
            if row and row["status"] == RunStatus.running.value:
                raise ApiError(409, ErrorCode.workflow_locked, "this step is already running")
            db.execute(
                "INSERT INTO step_runs (project_id, step, prompt, count, updated_at, status, "
                "error) VALUES (?, ?, ?, ?, ?, 'running', NULL) ON CONFLICT (project_id, step) "
                "DO UPDATE SET prompt = excluded.prompt, count = excluded.count, "
                "updated_at = excluded.updated_at, status = 'running', error = NULL",
                (project_id, key, prompt, count, _ts(now())),
            )

    def fail_run(self, project_id: str, key: str, error: str) -> None:
        with self._tx() as db:
            db.execute(
                "UPDATE step_runs SET status = 'failed', error = ?, updated_at = ? "
                "WHERE project_id = ? AND step = ? AND status = 'running'",
                (error, _ts(now()), project_id, key),
            )

    def fail_interrupted_runs(self) -> None:
        """Runs cut off by a restart (the model call is lost)."""
        with self._tx() as db:
            db.execute(
                "UPDATE step_runs SET status = 'failed', error = ?, updated_at = ? "
                "WHERE status = 'running'",
                ("interrupted by a server restart; run it again", _ts(now())),
            )

    def step_nodes(self, project_id: str, key: str) -> list[Node]:
        rows = self._all(
            "SELECT * FROM nodes WHERE project_id = ? AND workflow_step = ? "
            "AND deleted_at IS NULL ORDER BY workflow_item, created_at",
            project_id,
            key,
        )
        return [self._node(r) for r in rows]

    def node_inputs(self, node: Node) -> list[tuple[Node, Output]]:
        """What a node is generated from: the nodes its prompt mentions, and,
        through a one-to-one workflow edge, its source's image or video (a
        text source already became the prompt). Fails with
        ``missing_ref_output`` while one has no output."""
        inputs = []
        for edge in self.incoming_edges(node.id):
            source = self.get_node(edge.source_node_id)
            if source.selected_output_id is None:
                raise ApiError(
                    409,
                    ErrorCode.missing_ref_output,
                    f"referenced node {source.id} has no output yet; generate it first",
                    {"node_id": source.id},
                )
            output = self.get_output(source.selected_output_id)
            if edge.workflow and output.kind == MediaKind.text:
                continue
            inputs.append((source, output))
        return inputs

    def mentioned_nodes(self, project_id: str, text: str) -> list[Node]:
        """The nodes `text` mentions by ID, in order, that have an output."""
        with self._conn() as db:
            ids = self._id_map(db, project_id)
        found = []
        for node_id in mentioned(text, ids):
            node = self.get_node(node_id)
            if node.selected_output_id:
                found.append(node)
        return found

    def replace_step_nodes(
        self,
        project_id: str,
        key: str,
        prompt: str,
        items: list[str],
        count: int,
        sources: list[str] | None = None,
    ) -> tuple[list[Node], list[str]]:
        """Replace a step's nodes with one per item: a text step's nodes hold
        the item as their take; an image or video step's nodes get it as
        their prompt (to be generated). A one-to-one step's nodes get no ID.
        With `sources` (one node id per item), node i is wired to source i
        by a workflow edge. Returns (the new nodes, ids of jobs cancelled
        with the old ones)."""
        project = self.get_project(project_id)
        wf = project.workflow
        step = step_by_key(wf, key)
        if step is None:
            raise _not_found("workflow step", key)
        ids: list[str] = []
        with self._tx() as db:
            old = [
                r["id"]
                for r in db.execute(
                    "SELECT id FROM nodes WHERE project_id = ? AND workflow_step = ? "
                    "AND deleted_at IS NULL",
                    (project_id, key),
                )
            ]
            active = self._remove_workflow_nodes(db, old)
            for index, item in enumerate(items):
                node_id, ts = new_id("nod"), _ts(now())
                x, y = position_for(wf, key, index)
                name = (
                    ""
                    if step.output == OutputUse.one_to_one
                    else self._unique_name(db, project_id, f"{key}_{index + 1}", None)
                )
                text_step = step.kind == MediaKind.text
                db.execute(
                    "INSERT INTO nodes (id, project_id, kind, title, position, size, prompt, "
                    "params, selected_output_id, created_at, updated_at, workflow_step, "
                    "workflow_item) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?, ?, ?, ?)",
                    (
                        node_id,
                        project_id,
                        step.kind.value,
                        name,
                        Position(x=x, y=y).model_dump_json(),
                        "" if text_step else item,
                        default_params(step.kind).model_dump_json(),
                        ts,
                        ts,
                        key,
                        index + 1,
                    ),
                )
                if text_step:
                    self._insert_text_take(db, node_id, item)
                if sources is not None:
                    db.execute(
                        "INSERT INTO edges (id, project_id, source_node_id, target_node_id, "
                        "created_at, target_handle) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            new_id("edg"),
                            project_id,
                            sources[index],
                            node_id,
                            ts,
                            WORKFLOW_HANDLE,
                        ),
                    )
                ids.append(node_id)
            db.execute(
                "INSERT INTO step_runs (project_id, step, prompt, count, updated_at, status, "
                "error) VALUES (?, ?, ?, ?, ?, 'done', NULL) ON CONFLICT (project_id, step) "
                "DO UPDATE SET prompt = excluded.prompt, count = excluded.count, "
                "updated_at = excluded.updated_at, status = 'done', error = NULL",
                (project_id, key, prompt, count, _ts(now())),
            )
            self.sync_links(db, project_id)
            self._touch_project(db, project_id)
        return [self.get_node(i) for i in ids], active

    def _remove_workflow_nodes(self, db: Db, node_ids: list[str]) -> list[str]:
        """Soft-delete a step's old nodes (and their edges); returns the ids
        of jobs that were active on them."""
        ts = _ts(now())
        active: list[str] = []
        for node_id in node_ids:
            active += [
                r["id"]
                for r in db.execute(
                    f"SELECT id FROM jobs WHERE node_id = ? AND status IN {ACTIVE}", (node_id,)
                )
            ]
            db.execute(
                f"UPDATE jobs SET status = ?, error = ?, finished_at = ? "
                f"WHERE node_id = ? AND status IN {ACTIVE}",
                (JobStatus.canceled.value, "its step was run again", ts, node_id),
            )
            db.execute(
                "UPDATE edges SET deleted_at = ? WHERE deleted_at IS NULL "
                "AND (source_node_id = ? OR target_node_id = ?)",
                (ts, node_id, node_id),
            )
            db.execute("UPDATE nodes SET deleted_at = ? WHERE id = ?", (ts, node_id))
        return active

    @staticmethod
    def _insert_text_take(db: Db, node_id: str, text: str) -> str:
        """A take made without a job (a run's result, hand-written, or
        applied); it becomes the node's selected take."""
        output_id = new_id("out")
        db.execute(
            "INSERT INTO outputs (id, node_id, job_id, kind, text, asset_id, created_at) "
            "VALUES (?, ?, NULL, 'text', ?, NULL, ?)",
            (output_id, node_id, text, _ts(now())),
        )
        db.execute(
            "UPDATE nodes SET selected_output_id = ?, updated_at = ? WHERE id = ?",
            (output_id, _ts(now()), node_id),
        )
        return output_id

    def add_text_take(self, node_id: str, text: str) -> Output:
        """A hand-written (or applied) take for a text node."""
        node = self.get_node(node_id)
        if node.kind != MediaKind.text or node.source != NodeSource.generate:
            raise ApiError(409, ErrorCode.not_generatable, "only text nodes take written text")
        text = text.strip()
        if not text:
            raise ApiError(422, ErrorCode.validation_error, "the text is empty")
        with self._tx() as db:
            output_id = self._insert_text_take(db, node_id, text)
            self._touch_project(db, node.project_id)
        return self.get_output(output_id)
