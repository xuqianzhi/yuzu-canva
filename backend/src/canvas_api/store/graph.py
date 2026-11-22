"""Nodes, their IDs, edges, links that follow prompts, delete and restore."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from ..contract import (
    Edge,
    ErrorCode,
    JobStatus,
    Node,
    NodeCreate,
    NodeSource,
    NodeUpdate,
    Output,
    OutputUse,
    default_params,
    name_key,
    normalize_name,
)
from ..domain.mentions import (
    ID_RULE,
    is_valid_id,
    mentioned,
    remove_mentions,
    replace_mentions,
    to_valid_id,
)
from ..domain.workflow import (
    step_by_key,
)
from ..errors import ApiError
from ..ids import new_id
from .base import (
    ACTIVE,
    PURGE_AFTER,
    WORKFLOW_HANDLE,
    _not_found,
    _ts,
    now,
)


class GraphMixin:
    """Nodes, their IDs, edges, links that follow prompts, delete and restore."""

    def get_node(self, node_id: str) -> Node:
        row = self._one("SELECT * FROM nodes WHERE id = ? AND deleted_at IS NULL", node_id)
        if not row:
            raise _not_found("node", node_id)
        return self._node(row)

    def create_node(self, project_id: str, body: NodeCreate) -> Node:
        self.get_project(project_id)
        node_id, ts = new_id("nod"), _ts(now())
        params = body.params or default_params(body.kind)
        name = normalize_name(body.name)
        with self._tx() as db:
            self._check_name_free(db, project_id, name, None)
            db.execute(
                "INSERT INTO nodes (id, project_id, kind, title, position, size, prompt, "
                "params, selected_output_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    node_id,
                    project_id,
                    body.kind.value,
                    name or "",
                    body.position.model_dump_json(),
                    body.size.model_dump_json() if body.size else None,
                    body.prompt,
                    params.model_dump_json(),
                    ts,
                    ts,
                ),
            )
            self.sync_links(db, project_id)
            self._touch_project(db, project_id)
        return self.get_node(node_id)

    def update_node(self, node_id: str, body: NodeUpdate) -> Node:
        node = self.get_node(node_id)
        changes = body.model_fields_set
        if node.source == NodeSource.upload and (
            (body.kind is not None and body.kind != node.kind) or body.params is not None
        ):
            raise ApiError(
                422,
                ErrorCode.validation_error,
                "an uploaded node's kind and settings come from its file",
            )
        if node.workflow_step and "name" in changes:
            step = step_by_key(self.get_project(node.project_id).workflow, node.workflow_step)
            if step is not None and step.output == OutputUse.one_to_one:
                raise ApiError(
                    409,
                    ErrorCode.workflow_locked,
                    "a one-to-one step's nodes have no ID: only the next step uses them",
                    {"node_id": node_id},
                )
        if node.workflow_step and body.kind is not None and body.kind != node.kind:
            raise ApiError(
                409,
                ErrorCode.workflow_locked,
                "a workflow node's kind is set by its step",
                {"node_id": node_id},
            )
        name = normalize_name(body.name) if "name" in changes else node.name
        kind = body.kind or node.kind
        if body.params is not None:
            params = body.params
        elif kind != node.kind:
            params = default_params(kind)
        else:
            params = node.params
        if params.kind != kind:
            raise ApiError(
                422,
                ErrorCode.validation_error,
                f"params.kind {params.kind!r} does not match node kind {kind.value!r}",
            )

        selected = node.selected_output_id
        if "selected_output_id" in changes:
            selected = body.selected_output_id
            if selected is not None:
                output = self._one(
                    "SELECT kind FROM outputs WHERE id = ? AND node_id = ?", selected, node_id
                )
                if not output:
                    raise ApiError(
                        422,
                        ErrorCode.validation_error,
                        f"output {selected} is not a take of node {node_id}",
                    )
        if selected is not None:
            row = self._one("SELECT kind FROM outputs WHERE id = ?", selected)
            if row is None or row["kind"] != kind.value:
                selected = None

        size = body.size if "size" in changes else node.size
        with self._tx() as db:
            if "name" in changes:
                self._check_name_free(db, node.project_id, name, node_id)
                if node.name and name and name != node.name:
                    # Keep links: "@old" becomes "@new" in every prompt.
                    self._rename_mentions(db, node.project_id, node_id, node.name, name)
            db.execute(
                "UPDATE nodes SET kind = ?, title = ?, position = ?, size = ?, prompt = ?, "
                "params = ?, selected_output_id = ?, updated_at = ? WHERE id = ?",
                (
                    kind.value,
                    name or "",
                    (body.position or node.position).model_dump_json(),
                    size.model_dump_json() if size else None,
                    body.prompt if body.prompt is not None else node.prompt,
                    params.model_dump_json(),
                    selected,
                    _ts(now()),
                    node_id,
                ),
            )
            self.sync_links(db, node.project_id)
            self._touch_project(db, node.project_id)
        return self.get_node(node_id)

    @staticmethod
    def _names_in_use(
        db: sqlite3.Connection, project_id: str, exclude_id: str | None
    ) -> set[str]:
        rows = db.execute(
            "SELECT id, title FROM nodes WHERE project_id = ? AND deleted_at IS NULL "
            "AND title != ''",
            (project_id,),
        )
        return {name_key(r["title"]) for r in rows if r["id"] != exclude_id}

    def _check_name_free(
        self, db: sqlite3.Connection, project_id: str, name: str | None, node_id: str | None
    ) -> None:
        if name and not is_valid_id(name):
            raise ApiError(422, ErrorCode.validation_error, ID_RULE, {"name": name})
        if name and name_key(name) in self._names_in_use(db, project_id, node_id):
            raise ApiError(
                409,
                ErrorCode.duplicate_name,
                f"another node already has the ID “{name}”",
                {"name": name},
            )

    def _unique_name(
        self, db: sqlite3.Connection, project_id: str, wanted: str, node_id: str | None
    ) -> str:
        """`wanted` as a valid ID, or `wanted_2`, `wanted_3`... whichever is free."""
        base = wanted if is_valid_id(wanted) else to_valid_id(wanted)
        taken = self._names_in_use(db, project_id, node_id)
        candidate, n = base, 1
        while name_key(candidate) in taken:
            n += 1
            candidate = f"{base}_{n}"
        return candidate

    @staticmethod
    def _id_map(db: sqlite3.Connection, project_id: str) -> dict[str, str]:
        """Every live node's ID -> node id."""
        rows = db.execute(
            "SELECT id, title FROM nodes WHERE project_id = ? AND deleted_at IS NULL "
            "AND title != ''",
            (project_id,),
        )
        return {r["title"]: r["id"] for r in rows}

    def _rename_mentions(
        self, db: sqlite3.Connection, project_id: str, node_id: str, old: str, new: str
    ) -> None:
        ids = self._id_map(db, project_id)
        rows = db.execute(
            "SELECT id, prompt FROM nodes WHERE project_id = ? AND deleted_at IS NULL "
            "AND prompt != ''",
            (project_id,),
        ).fetchall()
        for r in rows:
            prompt = replace_mentions(
                r["prompt"], ids, lambda node, raw: new if node == node_id else raw
            )
            if prompt != r["prompt"]:
                db.execute("UPDATE nodes SET prompt = ? WHERE id = ?", (prompt, r["id"]))

    def sync_links(self, db: sqlite3.Connection, project_id: str) -> None:
        """Make links match prompts, for the whole project.

        - A generating node's links are exactly the nodes its prompt mentions by
          ID, minus any that would make a loop
          (those mentions stay unlinked; the UI says why).
        - Nothing may link out of a node without an ID: its links go.

        Links are soft-deleted and revived rather than re-created, so their
        ids survive undo/redo.
        """
        ts = _ts(now())
        nodes = db.execute(
            "SELECT id, title, prompt, role, source FROM nodes "
            "WHERE project_id = ? AND deleted_at IS NULL ORDER BY created_at, id",
            (project_id,),
        ).fetchall()
        ids = {r["title"]: r["id"] for r in nodes if r["title"]}
        named = set(ids.values())
        live = db.execute(
            "SELECT id, source_node_id, target_node_id, target_handle FROM edges "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchall()

        # Links out of nodes without an ID go, whatever input they feed --
        # except workflow edges, which belong to the workflow, not to IDs.
        for e in live:
            if e["source_node_id"] not in named and e["target_handle"] != WORKFLOW_HANDLE:
                db.execute("UPDATE edges SET deleted_at = ? WHERE id = ?", (ts, e["id"]))
        live = [
            e
            for e in live
            if e["source_node_id"] in named or e["target_handle"] == WORKFLOW_HANDLE
        ]

        wanted: list[tuple[str, str]] = []
        for r in nodes:
            if r["source"] != NodeSource.generate.value:
                continue
            for source in mentioned(r["prompt"], ids):
                if source != r["id"]:
                    wanted.append((source, r["id"]))
        wanted_set = set(wanted)

        kept = []
        for e in live:
            pair = (e["source_node_id"], e["target_node_id"])
            if e["target_handle"] == "" and pair not in wanted_set:
                db.execute("UPDATE edges SET deleted_at = ? WHERE id = ?", (ts, e["id"]))
            else:
                kept.append(pair)

        def reaches(start: str, goal: str, pairs: list[tuple[str, str]]) -> bool:
            stack, seen = [start], set()
            while stack:
                node = stack.pop()
                if node == goal:
                    return True
                if node not in seen:
                    seen.add(node)
                    stack.extend(t for s, t in pairs if s == node)
            return False

        present = {
            (e["source_node_id"], e["target_node_id"]) for e in live if e["target_handle"] == ""
        }
        for source, target in wanted:
            if (source, target) in present:
                continue
            if reaches(target, source, kept):
                continue  # would make a loop
            revived = db.execute(
                "UPDATE edges SET deleted_at = NULL WHERE source_node_id = ? "
                "AND target_node_id = ? AND target_handle = '' AND deleted_at IS NOT NULL",
                (source, target),
            ).rowcount
            if not revived:
                db.execute(
                    "INSERT INTO edges (id, project_id, source_node_id, target_node_id, "
                    "created_at, target_handle) VALUES (?, ?, ?, ?, ?, '')",
                    (new_id("edg"), project_id, source, target, ts),
                )
            kept.append((source, target))
            present.add((source, target))

    def sync_all_links(self) -> None:
        """Re-sync every project's links (on startup, e.g. after a migration
        changed how prompts mention IDs)."""
        projects = [r["id"] for r in self._all("SELECT id FROM projects")]
        for project_id in projects:
            with self._tx() as db:
                self.sync_links(db, project_id)

    def link_by_mention(self, source_id: str, target_id: str) -> Edge:
        """Link into a main input the only way it can exist: by mentioning
        the source in the target's prompt (its ID appended)."""
        source, target = self.get_node(source_id), self.get_node(target_id)
        with self._tx() as db:
            ids = self._id_map(db, target.project_id)
            if source_id not in mentioned(target.prompt, ids):
                prompt = f"{target.prompt.rstrip()} {source.name}".lstrip()
                db.execute(
                    "UPDATE nodes SET prompt = ?, updated_at = ? WHERE id = ?",
                    (prompt, _ts(now()), target_id),
                )
            self.sync_links(db, target.project_id)
            self._touch_project(db, target.project_id)
        row = self._one(
            "SELECT * FROM edges WHERE source_node_id = ? AND target_node_id = ? "
            "AND target_handle = '' AND deleted_at IS NULL",
            source_id,
            target_id,
        )
        if row is None:
            raise ApiError(409, ErrorCode.cycle, "linking these would make a loop")
        return self._edge(row)

    def delete_node(self, node_id: str) -> tuple[list[str], list[str]]:
        """Soft-delete a node and every live edge touching it; cancel its jobs.

        Nothing is erased until purge_deleted(), so restore() can undo it.
        Returns (ids of the edges deleted with it, ids of jobs that were active).
        """
        node = self.get_node(node_id)
        ts = _ts(now())
        with self._tx() as db:
            edges = [
                r["id"]
                for r in db.execute(
                    "SELECT id FROM edges WHERE deleted_at IS NULL "
                    "AND (source_node_id = ? OR target_node_id = ?)",
                    (node_id, node_id),
                )
            ]
            active = [
                r["id"]
                for r in db.execute(
                    f"SELECT id FROM jobs WHERE node_id = ? AND status IN {ACTIVE}", (node_id,)
                )
            ]
            db.execute(
                f"UPDATE jobs SET status = ?, error = ?, finished_at = ? "
                f"WHERE node_id = ? AND status IN {ACTIVE}",
                (JobStatus.canceled.value, "the node was deleted", ts, node_id),
            )
            db.execute(
                f"UPDATE edges SET deleted_at = ? WHERE id IN ({','.join('?' * len(edges))})",
                (ts, *edges),
            )
            db.execute("UPDATE nodes SET deleted_at = ? WHERE id = ?", (ts, node_id))
            self.sync_links(db, node.project_id)
            self._touch_project(db, node.project_id)
        return edges, active

    def restore(
        self, project_id: str, node_ids: list[str], edge_ids: list[str]
    ) -> tuple[list[Node], list[Edge], list[Output]]:
        """Undo soft deletes. Nodes first, then edges whose ends are live.

        An edge is skipped (stays deleted) if an identical live edge exists or
        it would now close a cycle. Returns what was restored, with the
        restored nodes' outputs.
        """
        from ..domain.graph import would_create_cycle  # avoid an import cycle

        self.get_project(project_id)
        with self._tx() as db:
            restored_nodes = []
            for node_id in dict.fromkeys(node_ids):
                row = db.execute(
                    "SELECT title FROM nodes "
                    "WHERE id = ? AND project_id = ? AND deleted_at IS NOT NULL",
                    (node_id, project_id),
                ).fetchone()
                if row is None:
                    continue
                # Its name may have been taken meanwhile: keep it unique.
                title = row["title"]
                if title:
                    title = self._unique_name(db, project_id, title, node_id)
                db.execute(
                    "UPDATE nodes SET deleted_at = NULL, title = ? WHERE id = ?",
                    (title, node_id),
                )
                restored_nodes.append(node_id)
            live = [
                self._edge(r)
                for r in db.execute(
                    "SELECT * FROM edges WHERE project_id = ? AND deleted_at IS NULL",
                    (project_id,),
                )
            ]
            restored_edges = []
            for edge_id in dict.fromkeys(edge_ids):
                row = db.execute(
                    "SELECT e.* FROM edges e "
                    "JOIN nodes s ON s.id = e.source_node_id AND s.deleted_at IS NULL "
                    "JOIN nodes t ON t.id = e.target_node_id AND t.deleted_at IS NULL "
                    "WHERE e.id = ? AND e.project_id = ? AND e.deleted_at IS NOT NULL",
                    (edge_id, project_id),
                ).fetchone()
                if row is None:
                    continue
                edge = self._edge(row)
                duplicate = any(
                    e.source_node_id == edge.source_node_id
                    and e.target_node_id == edge.target_node_id
                    and e.workflow == edge.workflow
                    for e in live
                )
                if duplicate or would_create_cycle(
                    live, edge.source_node_id, edge.target_node_id
                ):
                    continue
                db.execute("UPDATE edges SET deleted_at = NULL WHERE id = ?", (edge_id,))
                live.append(edge)
                restored_edges.append(edge)
            # Mentions of restored nodes link again (and their own prompts do);
            # a main-input link whose mention is gone does not survive this.
            self.sync_links(db, project_id)
            still = {
                r["id"]
                for r in db.execute(
                    "SELECT id FROM edges WHERE project_id = ? AND deleted_at IS NULL",
                    (project_id,),
                )
            }
            restored_edges = [e for e in restored_edges if e.id in still]
            if restored_nodes or restored_edges:
                self._touch_project(db, project_id)
        nodes = [self.get_node(n) for n in restored_nodes]
        outputs = [o for n in restored_nodes for o in self.list_outputs(n)]
        return nodes, restored_edges, outputs

    def purge_deleted(self, older_than: timedelta = PURGE_AFTER) -> list[Path]:
        """Erase nodes and edges soft-deleted before `older_than` ago.

        Returns the asset files of purged nodes, for the caller to remove.
        """
        cutoff = _ts(now() - older_than)
        with self._tx() as db:
            files = [
                self.assets_dir / r["filename"]
                for r in db.execute(
                    "SELECT a.filename FROM assets a JOIN outputs o ON o.asset_id = a.id "
                    "JOIN nodes n ON n.id = o.node_id "
                    "WHERE n.deleted_at IS NOT NULL AND n.deleted_at < ?",
                    (cutoff,),
                )
            ]
            db.execute(
                "DELETE FROM assets WHERE id IN (SELECT o.asset_id FROM outputs o "
                "JOIN nodes n ON n.id = o.node_id "
                "WHERE n.deleted_at IS NOT NULL AND n.deleted_at < ?)",
                (cutoff,),
            )
            db.execute(
                "DELETE FROM nodes WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,)
            )
            db.execute(
                "DELETE FROM edges WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,)
            )
        return files

    def project_edges(self, project_id: str) -> list[Edge]:
        rows = self._all(
            "SELECT * FROM edges WHERE project_id = ? AND deleted_at IS NULL", project_id
        )
        return [self._edge(r) for r in rows]

    def edge_by_id(self, edge_id: str) -> list[Edge]:
        """The live edge with this id, as a list (empty if none)."""
        row = self._one("SELECT * FROM edges WHERE id = ? AND deleted_at IS NULL", edge_id)
        return [self._edge(row)] if row else []

    def incoming_edges(self, node_id: str) -> list[Edge]:
        rows = self._all(
            "SELECT * FROM edges WHERE target_node_id = ? AND deleted_at IS NULL "
            "ORDER BY created_at, id",
            node_id,
        )
        return [self._edge(r) for r in rows]

    def delete_edge(self, edge_id: str) -> None:
        row = self._one("SELECT * FROM edges WHERE id = ? AND deleted_at IS NULL", edge_id)
        if not row:
            raise _not_found("edge", edge_id)
        with self._tx() as db:
            if row["target_handle"] == "":
                # A main-input link exists because the target's prompt has the
                # source's ID in it: remove those mentions, and the link follows.
                target = db.execute(
                    "SELECT prompt FROM nodes WHERE id = ?", (row["target_node_id"],)
                ).fetchone()
                ids = self._id_map(db, row["project_id"])
                prompt = remove_mentions(target["prompt"], ids, row["source_node_id"])
                db.execute(
                    "UPDATE nodes SET prompt = ?, updated_at = ? WHERE id = ?",
                    (prompt, _ts(now()), row["target_node_id"]),
                )
            # Soft: restore() can bring it back until purge_deleted().
            db.execute("UPDATE edges SET deleted_at = ? WHERE id = ?", (_ts(now()), edge_id))
            self.sync_links(db, row["project_id"])
            self._touch_project(db, row["project_id"])
