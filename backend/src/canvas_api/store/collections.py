"""Collections: the collection itself, members, invites, workflows, and the
one-tab-at-a-time lock on each project (see contract/collections.py)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from ..contract import (
    INVITE_DAYS,
    LOCK_SECONDS,
    Collection,
    CollectionCreate,
    CollectionSummary,
    CollectionUpdate,
    CollectionWorkflow,
    EditorLimits,
    ErrorCode,
    Invitation,
    Invite,
    InviteCreate,
    Member,
    ProjectLock,
    Role,
    RunStatus,
    WorkflowDefinition,
)
from ..domain.workflow import builtin_workflow
from ..errors import ApiError
from ..ids import new_id
from .base import ACTIVE, Db, Row, _dt, _not_found, _ts, now
from .media import asset_key, collection_key
from .users import _counts

_COLLECTION_SQL = (
    "SELECT c.*, o.email AS owner_email, u.email AS updated_by_email, m.role "
    "FROM collections c JOIN users o ON o.id = c.owner_id "
    "LEFT JOIN users u ON u.id = c.updated_by "
    "JOIN collection_members m ON m.collection_id = c.id AND m.user_id = ? "
)

_WORKFLOW_SQL = (
    "SELECT w.*, u.email AS updated_by_email, c.active_workflow_id "
    "FROM collection_workflows w JOIN collections c ON c.id = w.collection_id "
    "LEFT JOIN users u ON u.id = w.updated_by "
)


def _today() -> datetime:
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _limits(r: Row) -> EditorLimits:
    return EditorLimits(text=r["limit_text"], image=r["limit_image"], video=r["limit_video"])


def _forbidden(message: str) -> ApiError:
    return ApiError(403, ErrorCode.forbidden, message)


class CollectionsMixin:
    # --- collections -----------------------------------------------------------------

    @staticmethod
    def _collection(r: Row) -> Collection:
        return Collection(
            id=r["id"],
            name=r["name"],
            instruction=r["instruction"],
            active_workflow_id=r["active_workflow_id"],
            version=r["version"],
            your_role=r["role"],
            owner_email=r["owner_email"],
            updated_by_email=r["updated_by_email"],
            direct_image=bool(r["direct_image"]),
            direct_video=bool(r["direct_video"]),
            no_daily_limit=bool(r["no_daily_limit"]),
            created_at=_dt(r["created_at"]),
            updated_at=_dt(r["updated_at"]),
        )

    def list_collections(self, user_id: str) -> list[CollectionSummary]:
        """The collections you're in, most recently changed first."""
        rows = self._all(
            "SELECT c.*, o.email AS owner_email, u.email AS updated_by_email, m.role, "
            "(SELECT COUNT(*) FROM projects p WHERE p.collection_id = c.id) AS project_count, "
            "(SELECT COUNT(*) FROM collection_members x WHERE x.collection_id = c.id) "
            "AS member_count, "
            "GREATEST(c.updated_at, COALESCE((SELECT MAX(p.updated_at) FROM projects p "
            "WHERE p.collection_id = c.id), c.updated_at)) AS last_change "
            "FROM collections c JOIN users o ON o.id = c.owner_id "
            "LEFT JOIN users u ON u.id = c.updated_by "
            "JOIN collection_members m ON m.collection_id = c.id AND m.user_id = ? "
            "ORDER BY last_change DESC, c.id",
            user_id,
        )
        return [
            CollectionSummary(
                **self._collection(r).model_dump(),
                project_count=r["project_count"],
                member_count=r["member_count"],
            )
            for r in rows
        ]

    def get_collection(self, collection_id: str, user_id: str) -> Collection:
        row = self._one(_COLLECTION_SQL + "WHERE c.id = ?", user_id, collection_id)
        if row is None:
            raise _not_found("collection", collection_id)
        return self._collection(row)

    def create_collection(self, user_id: str, body: CollectionCreate) -> Collection:
        """A new collection, owned by `user_id`, with one (active) workflow."""
        collection_id, workflow_id, ts = new_id("col"), new_id("wfl"), _ts(now())
        definition = (body.workflow or builtin_workflow()).model_copy(
            update={"id": workflow_id, "version": 1}
        )
        with self._tx() as db:
            db.execute(
                "INSERT INTO collections (id, owner_id, name, instruction, active_workflow_id, "
                "version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (collection_id, user_id, body.name, body.instruction, workflow_id, ts, ts),
            )
            db.execute(
                "INSERT INTO collection_workflows (id, collection_id, definition, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?)",
                (workflow_id, collection_id, definition.model_dump_json(), ts, ts),
            )
            db.execute(
                "INSERT INTO collection_members (collection_id, user_id, role, created_at) "
                "VALUES (?, ?, 'owner', ?)",
                (collection_id, user_id, ts),
            )
        return self.get_collection(collection_id, user_id)

    def update_collection(
        self, collection_id: str, user_id: str, body: CollectionUpdate
    ) -> Collection:
        """Rename it, change its instruction or its settings; 409
        ``edit_conflict`` if it changed since ``body.version``."""
        with self._tx() as db:
            row = db.execute(
                "SELECT c.*, u.email AS updated_by_email FROM collections c "
                "LEFT JOIN users u ON u.id = c.updated_by WHERE c.id = ?",
                (collection_id,),
            ).fetchone()
            if row is None:
                raise _not_found("collection", collection_id)
            if row["version"] != body.version:
                who = row["updated_by_email"] or "someone"
                raise ApiError(
                    409,
                    ErrorCode.edit_conflict,
                    f"changed by {who} since you opened it; reload to see it",
                    {"version": str(row["version"]), "by": who},
                )
            db.execute(
                "UPDATE collections SET name = ?, instruction = ?, direct_image = ?, "
                "direct_video = ?, no_daily_limit = ?, version = version + 1, updated_by = ?, "
                "updated_at = ? "
                "WHERE id = ?",
                (
                    body.name if body.name is not None else row["name"],
                    body.instruction if body.instruction is not None else row["instruction"],
                    body.direct_image if body.direct_image is not None else row["direct_image"],
                    body.direct_video if body.direct_video is not None else row["direct_video"],
                    body.no_daily_limit
                    if body.no_daily_limit is not None
                    else row["no_daily_limit"],
                    user_id,
                    _ts(now()),
                    collection_id,
                ),
            )
        return self.get_collection(collection_id, user_id)

    def delete_collection(self, collection_id: str) -> tuple[list[str], list[str]]:
        """Delete it with every project in it (see DEPLOY/design notes).

        Returns (files to remove, ids of jobs that were active)."""
        with self._tx() as db:
            if not db.execute(
                "SELECT 1 FROM collections WHERE id = ?", (collection_id,)
            ).fetchone():
                raise _not_found("collection", collection_id)
            files = [
                asset_key(r["filename"])
                for r in db.execute(
                    "SELECT a.filename FROM assets a JOIN projects p ON p.id = a.project_id "
                    "WHERE p.collection_id = ?",
                    (collection_id,),
                )
            ]
            files += [
                collection_key(r["filename"])
                for r in db.execute(
                    "SELECT filename FROM collection_assets WHERE collection_id = ?",
                    (collection_id,),
                )
            ]
            active = [
                r["id"]
                for r in db.execute(
                    f"SELECT j.id FROM jobs j JOIN projects p ON p.id = j.project_id "
                    f"WHERE p.collection_id = ? AND j.status IN {ACTIVE}",
                    (collection_id,),
                )
            ]
            db.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        return files, active

    # --- members ---------------------------------------------------------------------

    def list_members(self, collection_id: str) -> list[Member]:
        """The owner first, then editors in the order they joined."""
        rows = self._all(
            "SELECT m.*, u.email FROM collection_members m JOIN users u ON u.id = m.user_id "
            "WHERE m.collection_id = ? ORDER BY m.role = 'owner' DESC, m.created_at, u.email",
            collection_id,
        )
        today = _today()
        return [
            Member(
                user_id=r["user_id"],
                email=r["email"],
                role=r["role"],
                limits=_limits(r),
                used_today=_counts(self.usage_in(collection_id, r["user_id"], today)),
                joined_at=_dt(r["created_at"]),
            )
            for r in rows
        ]

    def get_member(self, collection_id: str, user_id: str) -> Member:
        for member in self.list_members(collection_id):
            if member.user_id == user_id:
                return member
        raise _not_found("member", user_id)

    def member_limits(self, collection_id: str, user_id: str) -> EditorLimits | None:
        """An editor's own limits here (None for the owner, or a non-member)."""
        row = self._one(
            "SELECT * FROM collection_members WHERE collection_id = ? AND user_id = ?",
            collection_id,
            user_id,
        )
        if row is None or row["role"] == Role.owner.value:
            return None
        return _limits(row)

    def set_member_limits(
        self, collection_id: str, user_id: str, limits: EditorLimits
    ) -> Member:
        member = self.get_member(collection_id, user_id)
        if member.role == Role.owner:
            raise ApiError(
                409,
                ErrorCode.validation_error,
                "the owner has no limits of their own here (only the daily limits)",
            )
        with self._tx() as db:
            db.execute(
                "UPDATE collection_members SET limit_text = ?, limit_image = ?, "
                "limit_video = ? WHERE collection_id = ? AND user_id = ?",
                (limits.text, limits.image, limits.video, collection_id, user_id),
            )
        return self.get_member(collection_id, user_id)

    def remove_member(self, collection_id: str, user_id: str) -> None:
        """An editor leaves (or is removed); what they made stays. Their
        locks in the collection are released."""
        member = self.get_member(collection_id, user_id)
        if member.role == Role.owner:
            raise ApiError(
                409, ErrorCode.validation_error, "the owner can't leave their own collection"
            )
        with self._tx() as db:
            db.execute(
                "DELETE FROM collection_members WHERE collection_id = ? AND user_id = ?",
                (collection_id, user_id),
            )
            db.execute(
                "DELETE FROM project_locks WHERE user_id = ? AND project_id IN "
                "(SELECT id FROM projects WHERE collection_id = ?)",
                (user_id, collection_id),
            )

    # --- invites ---------------------------------------------------------------------

    @staticmethod
    def _drop_expired(db: Db) -> None:
        db.execute("DELETE FROM collection_invites WHERE expires_at <= ?", (_ts(now()),))

    def list_invites(self, collection_id: str) -> list[Invite]:
        """Invites not accepted (or declined) yet, newest first."""
        rows = self._all(
            "SELECT i.*, u.email AS invited_by_email FROM collection_invites i "
            "JOIN users u ON u.id = i.invited_by "
            "WHERE i.collection_id = ? AND i.expires_at > ? "
            "ORDER BY i.created_at DESC, i.id",
            collection_id,
            _ts(now()),
        )
        return [
            Invite(
                id=r["id"],
                email=r["email"],
                limits=_limits(r),
                invited_by_email=r["invited_by_email"],
                created_at=_dt(r["created_at"]),
                expires_at=_dt(r["expires_at"]),
            )
            for r in rows
        ]

    def create_invite(self, collection_id: str, inviter: str, body: InviteCreate) -> Invite:
        """Invite an email as an editor. Inviting it again renews the invite
        (and its limits)."""
        email = body.email.strip().lower()
        ts, expires = now(), now() + timedelta(days=INVITE_DAYS)
        with self._tx() as db:
            self._drop_expired(db)
            if db.execute(
                "SELECT 1 FROM collection_members m JOIN users u ON u.id = m.user_id "
                "WHERE m.collection_id = ? AND lower(u.email) = ?",
                (collection_id, email),
            ).fetchone():
                raise ApiError(
                    409, ErrorCode.validation_error, f"{email} is already in this collection"
                )
            limits = body.limits
            db.execute(
                "INSERT INTO collection_invites (id, collection_id, email, invited_by, "
                "limit_text, limit_image, limit_video, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (collection_id, email) DO UPDATE SET "
                "invited_by = excluded.invited_by, limit_text = excluded.limit_text, "
                "limit_image = excluded.limit_image, limit_video = excluded.limit_video, "
                "created_at = excluded.created_at, expires_at = excluded.expires_at",
                (
                    new_id("inv"),
                    collection_id,
                    email,
                    inviter,
                    limits.text,
                    limits.image,
                    limits.video,
                    _ts(ts),
                    _ts(expires),
                ),
            )
        return next(i for i in self.list_invites(collection_id) if i.email == email)

    def cancel_invite(self, collection_id: str, invite_id: str) -> None:
        with self._tx() as db:
            deleted = db.execute(
                "DELETE FROM collection_invites WHERE id = ? AND collection_id = ?",
                (invite_id, collection_id),
            ).rowcount
        if not deleted:
            raise _not_found("invite", invite_id)

    def invitations_for(self, email: str) -> list[Invitation]:
        rows = self._all(
            "SELECT i.*, c.name AS collection_name, u.email AS invited_by_email "
            "FROM collection_invites i JOIN collections c ON c.id = i.collection_id "
            "JOIN users u ON u.id = i.invited_by "
            "WHERE i.email = ? AND i.expires_at > ? ORDER BY i.created_at DESC, i.id",
            email.strip().lower(),
            _ts(now()),
        )
        return [
            Invitation(
                id=r["id"],
                collection_id=r["collection_id"],
                collection_name=r["collection_name"],
                invited_by_email=r["invited_by_email"],
                created_at=_dt(r["created_at"]),
                expires_at=_dt(r["expires_at"]),
            )
            for r in rows
        ]

    def _my_invite(self, db: Db, invite_id: str, email: str) -> Row:
        row = db.execute(
            "SELECT * FROM collection_invites WHERE id = ? AND email = ? AND expires_at > ?",
            (invite_id, email.strip().lower(), _ts(now())),
        ).fetchone()
        if row is None:  # someone else's invites don't exist for you
            raise _not_found("invite", invite_id)
        return row

    def accept_invite(self, invite_id: str, user_id: str, email: str) -> Collection:
        """Join the collection as an editor, with the invite's limits."""
        with self._tx() as db:
            invite = self._my_invite(db, invite_id, email)
            db.execute(
                "INSERT INTO collection_members (collection_id, user_id, role, limit_text, "
                "limit_image, limit_video, created_at) VALUES (?, ?, 'editor', ?, ?, ?, ?) "
                "ON CONFLICT (collection_id, user_id) DO NOTHING",
                (
                    invite["collection_id"],
                    user_id,
                    invite["limit_text"],
                    invite["limit_image"],
                    invite["limit_video"],
                    _ts(now()),
                ),
            )
            db.execute("DELETE FROM collection_invites WHERE id = ?", (invite_id,))
        return self.get_collection(invite["collection_id"], user_id)

    def decline_invite(self, invite_id: str, email: str) -> None:
        with self._tx() as db:
            self._my_invite(db, invite_id, email)
            db.execute("DELETE FROM collection_invites WHERE id = ?", (invite_id,))

    # --- workflows -------------------------------------------------------------------

    @staticmethod
    def _workflow(r: Row) -> CollectionWorkflow:
        return CollectionWorkflow(
            id=r["id"],
            collection_id=r["collection_id"],
            definition=WorkflowDefinition.model_validate_json(r["definition"]),
            active=r["id"] == r["active_workflow_id"],
            updated_by_email=r["updated_by_email"],
            created_at=_dt(r["created_at"]),
            updated_at=_dt(r["updated_at"]),
        )

    def list_workflows(self, collection_id: str) -> list[CollectionWorkflow]:
        """Oldest first."""
        rows = self._all(
            _WORKFLOW_SQL + "WHERE w.collection_id = ? ORDER BY w.created_at, w.id",
            collection_id,
        )
        return [self._workflow(r) for r in rows]

    def get_workflow(self, workflow_id: str) -> CollectionWorkflow:
        row = self._one(_WORKFLOW_SQL + "WHERE w.id = ?", workflow_id)
        if row is None:
            raise _not_found("workflow", workflow_id)
        return self._workflow(row)

    @staticmethod
    def _refuse_while_running(db: Db, collection_id: str) -> None:
        """The active workflow can't change under a running step."""
        if db.execute(
            "SELECT 1 FROM step_runs r JOIN projects p ON p.id = r.project_id "
            "WHERE p.collection_id = ? AND r.status = ? LIMIT 1",
            (collection_id, RunStatus.running.value),
        ).fetchone():
            raise ApiError(
                409,
                ErrorCode.workflow_locked,
                "a step is running in this collection; wait for it to finish",
            )

    def create_workflow(
        self, collection_id: str, user_id: str, definition: WorkflowDefinition
    ) -> CollectionWorkflow:
        """A new (inactive) workflow in the collection."""
        workflow_id, ts = new_id("wfl"), _ts(now())
        saved = definition.model_copy(update={"id": workflow_id, "version": 1})
        with self._tx() as db:
            db.execute(
                "INSERT INTO collection_workflows (id, collection_id, definition, updated_by, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (workflow_id, collection_id, saved.model_dump_json(), user_id, ts, ts),
            )
        return self.get_workflow(workflow_id)

    def update_workflow(
        self,
        workflow_id: str,
        user_id: str,
        definition: WorkflowDefinition,
        base_version: int | None,
    ) -> CollectionWorkflow:
        """Replace a workflow (its version goes up by one)."""
        current = self.get_workflow(workflow_id)
        with self._tx() as db:
            row = db.execute(
                "SELECT definition FROM collection_workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
            version = json.loads(row["definition"]).get("version", 0)
            if base_version is not None and base_version != version:
                who = current.updated_by_email or "someone"
                raise ApiError(
                    409,
                    ErrorCode.edit_conflict,
                    f"changed by {who} since you opened it; reload to see it",
                    {"version": str(version), "by": who},
                )
            if current.active:
                self._refuse_while_running(db, current.collection_id)
            saved = definition.model_copy(update={"id": workflow_id, "version": version + 1})
            db.execute(
                "UPDATE collection_workflows SET definition = ?, updated_by = ?, "
                "updated_at = ? WHERE id = ?",
                (saved.model_dump_json(), user_id, _ts(now()), workflow_id),
            )
        return self.get_workflow(workflow_id)

    def delete_workflow(self, workflow_id: str) -> None:
        if self.get_workflow(workflow_id).active:
            raise ApiError(
                409,
                ErrorCode.validation_error,
                "this is the active workflow: make another one active first",
            )
        with self._tx() as db:
            db.execute("DELETE FROM collection_workflows WHERE id = ?", (workflow_id,))

    def activate_workflow(self, workflow_id: str) -> CollectionWorkflow:
        """Every project in the collection runs on this one from now on."""
        workflow = self.get_workflow(workflow_id)
        if workflow.active:
            return workflow
        with self._tx() as db:
            self._refuse_while_running(db, workflow.collection_id)
            db.execute(
                "UPDATE collections SET active_workflow_id = ?, updated_at = ? WHERE id = ?",
                (workflow_id, _ts(now()), workflow.collection_id),
            )
        return self.get_workflow(workflow_id)

    # --- project locks -------------------------------------------------------------------

    @staticmethod
    def _live_lock(db: Db, project_id: str) -> Row | None:
        row = db.execute(
            "SELECT l.*, u.email FROM project_locks l JOIN users u ON u.id = l.user_id "
            "WHERE l.project_id = ?",
            (project_id,),
        ).fetchone()
        return row if row and row["expires_at"] > _ts(now()) else None

    @staticmethod
    def _lock_view(project_id: str, row: Row | None, user_id: str, session: str | None):
        if row is None:
            return ProjectLock(project_id=project_id, held=False)
        mine = row["user_id"] == user_id
        return ProjectLock(
            project_id=project_id,
            held=mine and row["session_id"] == session,
            holder_email=row["email"],
            holder_is_you=mine,
            expires_at=_dt(row["expires_at"]),
        )

    @staticmethod
    def _locked(row: Row, user_id: str) -> ApiError:
        mine = row["user_id"] == user_id
        message = (
            "you're editing this project somewhere else"
            if mine
            else f"{row['email']} is editing this project"
        )
        return ApiError(
            409,
            ErrorCode.project_locked,
            message,
            {"holder_email": row["email"], "holder_is_you": "true" if mine else "false"},
        )

    def acquire_lock(
        self, project_id: str, user_id: str, session: str | None, take_over: bool = False
    ) -> ProjectLock:
        """Take or renew the project's lock for this tab (`session`): free,
        expired, already this tab's, or (with `take_over`) your own other
        tab's. Otherwise 409 ``project_locked``."""
        if not session:
            raise ApiError(
                409,
                ErrorCode.project_locked,
                "open the project in the app to change it (no edit session)",
            )
        with self._tx() as db:
            row = self._live_lock(db, project_id)
            if row is not None and not (
                row["user_id"] == user_id and (row["session_id"] == session or take_over)
            ):
                raise self._locked(row, user_id)
            expires = _ts(now() + timedelta(seconds=LOCK_SECONDS))
            db.execute(
                "INSERT INTO project_locks (project_id, user_id, session_id, expires_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (project_id) DO UPDATE SET "
                "user_id = excluded.user_id, session_id = excluded.session_id, "
                "expires_at = excluded.expires_at",
                (project_id, user_id, session, expires),
            )
            row = self._live_lock(db, project_id)
        return self._lock_view(project_id, row, user_id, session)

    def lock_status(self, project_id: str, user_id: str, session: str | None) -> ProjectLock:
        with self._conn() as db:
            row = self._live_lock(db, project_id)
        return self._lock_view(project_id, row, user_id, session)

    def release_lock(self, project_id: str, user_id: str, session: str | None) -> None:
        """Let go of the lock, if this tab holds it."""
        with self._tx() as db:
            db.execute(
                "DELETE FROM project_locks WHERE project_id = ? AND user_id = ? "
                "AND session_id = ?",
                (project_id, user_id, session or ""),
            )

    def editing_now(self, collection_id: str) -> dict[str, tuple[str, str]]:
        """Projects in the collection someone is editing: {project id:
        (user id, email)}."""
        rows = self._all(
            "SELECT l.project_id, l.user_id, u.email FROM project_locks l "
            "JOIN users u ON u.id = l.user_id JOIN projects p ON p.id = l.project_id "
            "WHERE p.collection_id = ? AND l.expires_at > ?",
            collection_id,
            _ts(now()),
        )
        return {r["project_id"]: (r["user_id"], r["email"]) for r in rows}
