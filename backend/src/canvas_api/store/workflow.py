"""Running a project's workflow steps."""

from __future__ import annotations

from ..contract import (
    Asset,
    Carry,
    ErrorCode,
    JobStatus,
    MediaKind,
    Node,
    NodeParams,
    NodeSource,
    Output,
    Position,
    Project,
    RunStatus,
    StepEntry,
    StepRun,
    default_params,
    name_key,
)
from ..domain.mentions import (
    mentioned,
    to_valid_id,
)
from ..domain.workflow import (
    position_for,
    step_by_key,
)
from ..errors import ApiError
from ..files import delete_all
from ..ids import new_id
from .base import (
    ACTIVE,
    Db,
    _dt,
    _not_found,
    _ts,
    now,
)
from .media import _ext


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
                manual=bool(r["manual"]),
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
                "updated_at = excluded.updated_at, status = 'running', error = NULL, "
                "manual = FALSE",
                (project_id, key, prompt, count, _ts(now())),
            )

    def fail_run(self, project_id: str, key: str, error: str) -> None:
        with self._tx() as db:
            db.execute(
                "UPDATE step_runs SET status = 'failed', error = ?, updated_at = ? "
                "WHERE project_id = ? AND step = ? AND status = 'running'",
                (error, _ts(now()), project_id, key),
            )

    def finish_run(self, project_id: str, key: str) -> None:
        """A run left ``running`` by replace_step_nodes(done=False) is done."""
        with self._tx() as db:
            db.execute(
                "UPDATE step_runs SET status = 'done', updated_at = ? "
                "WHERE project_id = ? AND step = ? AND status = 'running'",
                (_ts(now()), project_id, key),
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
        through a workflow edge (kept on existing data), its source's image or
        video (a text source already became the prompt). Fails with
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

    def mentioned_nodes(self, project_id: str, text: str) -> list[tuple[Node, Output]]:
        """The nodes `text` mentions by ID, in order, with their chosen takes
        (those with none are left out)."""
        with self._conn() as db:
            ids = self._id_map(db, project_id)
        found = mentioned(text, ids)
        if not found:
            return []
        marks = ", ".join("?" * len(found))
        rows = self._all(
            f"SELECT * FROM nodes WHERE id IN ({marks}) AND deleted_at IS NULL "
            "AND selected_output_id IS NOT NULL",
            *found,
        )
        nodes = {r["id"]: self._node(r) for r in rows}
        outputs = self.outputs_by_id([n.selected_output_id for n in nodes.values()])
        return [
            (nodes[i], outputs[nodes[i].selected_output_id])
            for i in found
            if i in nodes and nodes[i].selected_output_id in outputs
        ]

    def carried_forward(self, project: Project, key: str) -> list[tuple[str, Node, Output]]:
        """What earlier steps settled on, for a run (or chat) of step `key`:
        (step name, node, its chosen take) for each earlier step's results
        that have one, in step order -- all of them, or for a step that
        carries only what's used, those used (see Carry). Steps that carry
        nothing aren't even read."""
        steps = project.workflow.steps
        index = next((i for i, s in enumerate(steps) if s.key == key), None)
        if index is None:
            return []
        earlier = [s for s in steps[:index] if s.carry != Carry.none]
        if not earlier:
            return []
        marks = ", ".join("?" * len(earlier))
        rows = self._all(
            f"SELECT * FROM nodes WHERE project_id = ? AND workflow_step IN ({marks}) "
            "AND deleted_at IS NULL AND selected_output_id IS NOT NULL "
            "ORDER BY workflow_item, created_at",
            project.id,
            *(s.key for s in earlier),
        )
        by_step: dict[str, list[Node]] = {}
        for r in rows:
            by_step.setdefault(r["workflow_step"], []).append(self._node(r))
        used = (
            self._used_nodes(project.id)
            if any(s.carry == Carry.used for s in earlier)
            else set()
        )
        chosen = [
            (s.name, n)
            for s in earlier
            for n in by_step.get(s.key, [])
            if s.carry != Carry.used or n.id in used
        ]
        outputs = self.outputs_by_id([n.selected_output_id for _, n in chosen])
        return [
            (name, n, outputs[n.selected_output_id])
            for name, n in chosen
            if n.selected_output_id in outputs
        ]

    def _used_nodes(self, project_id: str) -> set[str]:
        """Nodes something else uses: a link's source (a node prompt that
        mentions it, or an old workflow edge), or mentioned in the prompt of
        another step's run."""
        with self._conn() as db:
            ids = self._id_map(db, project_id)
            used = {
                r["source_node_id"]
                for r in db.execute(
                    "SELECT source_node_id FROM edges WHERE project_id = ? "
                    "AND deleted_at IS NULL",
                    (project_id,),
                )
            }
            step_of = {
                r["id"]: r["workflow_step"]
                for r in db.execute(
                    "SELECT id, workflow_step FROM nodes WHERE project_id = ? "
                    "AND deleted_at IS NULL",
                    (project_id,),
                )
            }
            runs = db.execute(
                "SELECT step, prompt FROM step_runs WHERE project_id = ?", (project_id,)
            ).fetchall()
        for run in runs:
            used.update(
                n for n in mentioned(run["prompt"], ids) if step_of.get(n) != run["step"]
            )
        return used

    def node_names(self, project_id: str) -> list[str]:
        """Every live node's ID in the project."""
        with self._conn() as db:
            return sorted(self._id_map(db, project_id))

    def _step_names(
        self,
        db: Db,
        project_id: str,
        key: str,
        items: list[str],
        given: list[str | None] | None,
        media: bool,
    ) -> list[str]:
        """IDs for a step's new nodes (its old ones already gone): each the
        name the model gave, made valid and short, else ``<step>_<n>``; then
        ``_2``, ``_3``... while it's taken, ignoring case.

        In an image or video step, a node whose ID is written in a sibling's
        prompt would be that sibling's input before it has an output, and
        the sibling's generation would fail: it gets its number added
        (``怪人`` -> ``怪人_1``)."""
        taken = self._names_in_use(db, project_id, None)
        names: list[str] = []
        for index in range(len(items)):
            wanted = _clean_name((given or [None] * len(items))[index]) or f"{key}_{index + 1}"
            names.append(_free(wanted, taken))
        if media and len(items) > 1:
            ids = {**self._id_map(db, project_id), **{n: f"#{i}" for i, n in enumerate(names)}}
            for index, name in enumerate(names):
                if any(
                    f"#{index}" in mentioned(item, ids)
                    for other, item in enumerate(items)
                    if other != index
                ):
                    taken.discard(name_key(name))
                    names[index] = _free(f"{name}_{index + 1}", taken)
        return names

    def replace_step_nodes(
        self,
        project_id: str,
        key: str,
        prompt: str,
        items: list[str],
        count: int,
        names: list[str | None] | None = None,
        files: list[tuple[Asset, str]] | None = None,
        manual: bool = False,
        params: list[NodeParams | None] | None = None,
        done: bool = True,
    ) -> tuple[list[Node], list[str]]:
        """Replace a step's nodes with one per item: a text step's nodes hold
        the item as their take; an image or video step's nodes get it as
        their prompt (to be generated), or, with `files` (an asset and its
        file's key per item), a copy of that file as their take instead. `names` are
        the IDs given to the items (see _step_names). `manual`: completed by
        hand (the run's prompt is then left as it was). `params`: each
        node's settings (None: the defaults). `done`: False leaves the run
        ``running`` (something follows; ``finish_run`` ends it). Returns (the new nodes, ids
        of jobs cancelled with the old ones)."""
        written: list[str] = []
        try:
            return self._replace_step_nodes(
                project_id,
                key,
                prompt,
                items,
                count,
                names,
                files,
                manual,
                params,
                written,
                done,
            )
        except BaseException:
            delete_all(self.files, written)
            raise

    def _replace_step_nodes(
        self,
        project_id: str,
        key: str,
        prompt: str,
        items: list[str],
        count: int,
        names: list[str | None] | None,
        files: list[tuple[Asset, str]] | None,
        manual: bool,
        params: list[NodeParams | None] | None,
        written: list[str],
        done: bool = True,
    ) -> tuple[list[Node], list[str]]:
        project = self.get_project(project_id)
        wf = project.workflow
        step = step_by_key(wf, key)
        if step is None:
            raise _not_found("workflow step", key)
        ids: list[str] = []
        with self._tx() as db:
            if manual:
                running = db.execute(
                    "SELECT 1 FROM step_runs WHERE project_id = ? AND step = ? AND status = ?",
                    (project_id, key, RunStatus.running.value),
                ).fetchone()
                if running:
                    raise ApiError(409, ErrorCode.workflow_locked, "this step is running")
            old = [
                r["id"]
                for r in db.execute(
                    "SELECT id FROM nodes WHERE project_id = ? AND workflow_step = ? "
                    "AND deleted_at IS NULL",
                    (project_id, key),
                )
            ]
            active = self._remove_workflow_nodes(db, old)
            titles = self._step_names(
                db, project_id, key, items, names, media=step.kind != MediaKind.text
            )
            for index, item in enumerate(items):
                node_id, ts = new_id("nod"), _ts(now())
                x, y = position_for(wf, key, index)
                name = titles[index]
                text_step = step.kind == MediaKind.text
                file = files[index] if files else None
                settings = (params[index] if params else None) or default_params(step.kind)
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
                        "" if text_step or file else item,
                        settings.model_dump_json(),
                        ts,
                        ts,
                        key,
                        index + 1,
                    ),
                )
                if text_step:
                    self._insert_text_take(db, node_id, item)
                elif file is not None:
                    written.append(self._insert_file_take(db, project_id, node_id, *file))
                ids.append(node_id)
            # By hand, the last run's prompt stays (for running it again).
            keep = "step_runs.prompt" if manual else "excluded.prompt"
            db.execute(
                "INSERT INTO step_runs (project_id, step, prompt, count, updated_at, status, "
                "error, manual) VALUES (?, ?, ?, ?, ?, ?, NULL, ?) "
                "ON CONFLICT (project_id, step) "
                f"DO UPDATE SET prompt = {keep}, count = excluded.count, "
                "updated_at = excluded.updated_at, status = excluded.status, error = NULL, "
                "manual = excluded.manual",
                (
                    project_id,
                    key,
                    prompt,
                    count,
                    _ts(now()),
                    RunStatus.done.value if done else RunStatus.running.value,
                    manual,
                ),
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

    def _insert_file_take(
        self, db: Db, project_id: str, node_id: str, asset: Asset, source: str
    ) -> str:
        """A copy of an uploaded file as the node's take, selected. Returns
        the key of the file written."""
        asset_id, key = self._insert_asset(
            db,
            project_id,
            asset.kind,
            asset.mime,
            _ext(source),
            asset.bytes,
            asset.width,
            asset.height,
            asset.duration_s,
            copy_from=source,
        )
        output_id, ts = new_id("out"), _ts(now())
        db.execute(
            "INSERT INTO outputs (id, node_id, job_id, kind, text, asset_id, created_at) "
            "VALUES (?, ?, NULL, ?, NULL, ?, ?)",
            (output_id, node_id, asset.kind.value, asset_id, ts),
        )
        db.execute(
            "UPDATE nodes SET selected_output_id = ?, updated_at = ? WHERE id = ?",
            (output_id, ts, node_id),
        )
        return key

    def complete_step(
        self, project_id: str, key: str, entries: list[StepEntry]
    ) -> tuple[list[Node], list[str]]:
        """A step's nodes from the user's own results (see StepCompleteRequest):
        nothing is generated. Returns (the new nodes, ids of jobs cancelled
        with the old ones)."""
        step = step_by_key(self.get_project(project_id).workflow, key)
        if step is None:
            raise _not_found("workflow step", key)
        files: list[tuple[Asset, str]] = []
        for n, entry in enumerate(entries, start=1):
            if step.kind == MediaKind.text:
                if entry.text is None or not entry.text.strip():
                    raise ApiError(422, ErrorCode.validation_error, f"result {n}: write text")
                continue
            if entry.material_id is None:
                raise ApiError(
                    422, ErrorCode.validation_error, f"result {n}: upload a {step.kind.value}"
                )
            material = self.get_material(entry.material_id)
            if material.project_id != project_id:
                raise _not_found("material", entry.material_id)
            if material.asset.kind != step.kind:
                raise ApiError(
                    422,
                    ErrorCode.validation_error,
                    f"result {n}: this step takes a {step.kind.value}, "
                    f"not a {material.asset.kind.value}",
                )
            files.append(self.asset_file(material.asset.id))
        return self.replace_step_nodes(
            project_id,
            key,
            "",
            [(e.text or "").strip() for e in entries],
            len(entries),
            names=[e.id for e in entries],
            files=files or None,
            manual=True,
        )

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
            if node.workflow_step:
                db.execute("UPDATE nodes SET edited = TRUE WHERE id = ?", (node_id,))
            self._touch_project(db, node.project_id)
        return self.get_output(output_id)


# The most of a model-given name that is kept.
GIVEN_NAME_MAX = 24


def _clean_name(name: str | None) -> str:
    """A model-given name as a valid ID ("" if nothing usable is left)."""
    if not name or not name.strip():
        return ""
    cleaned = to_valid_id(name)[:GIVEN_NAME_MAX].strip("_-")
    return "" if cleaned == "node" and name.strip().lower() != "node" else cleaned


def _free(wanted: str, taken: set[str]) -> str:
    """`wanted`, or `wanted_2`, `wanted_3`...: the first not in `taken`
    (which it is then added to)."""
    candidate, n = wanted, 1
    while name_key(candidate) in taken:
        n += 1
        candidate = f"{wanted}_{n}"
    taken.add(name_key(candidate))
    return candidate
