"""Shared objects for routes, created by the app lifespan; and who's calling."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool

from .auth import Authenticator, User
from .config import Settings
from .contract import EDIT_SESSION_HEADER, ErrorCode, Role
from .errors import ApiError
from .files import Files
from .jobs.worker import Worker
from .providers.openai_text import TextModel
from .spending import Spending
from .store import Store


def _store(request: Request) -> Store:
    return request.app.state.store


def _worker(request: Request) -> Worker:
    return request.app.state.worker


def _text_model(request: Request) -> TextModel:
    return request.app.state.text_model


def _files(request: Request) -> Files:
    return request.app.state.store.files


def _spending(request: Request) -> Spending:
    return request.app.state.spending


def _settings(request: Request) -> Settings:
    return request.app.state.settings


StoreDep = Annotated[Store, Depends(_store)]
TextModelDep = Annotated[TextModel, Depends(_text_model)]
WorkerDep = Annotated[Worker, Depends(_worker)]
FilesDep = Annotated[Files, Depends(_files)]
SpendingDep = Annotated[Spending, Depends(_spending)]
SettingsDep = Annotated[Settings, Depends(_settings)]

# A user's row is refreshed (last seen, email) at most this often.
_SEEN_EVERY_S = 600


async def _current_user(request: Request) -> User:
    auth: Authenticator = request.app.state.auth
    user = await run_in_threadpool(auth.user, request.headers.get("authorization"))
    seen: dict[str, float] = request.app.state.seen_users
    if time.monotonic() - seen.get(user.id, -_SEEN_EVERY_S) >= _SEEN_EVERY_S:
        await run_in_threadpool(request.app.state.store.ensure_user, user.id, user.email)
        seen[user.id] = time.monotonic()
    return user


UserDep = Annotated[User, Depends(_current_user)]

# What every ID looks like ("prj_x1y2", see ids.py).
_WELL_FORMED = re.compile(r"^[a-z]{3}_[A-Za-z0-9]+$")

# Path parameters that name something in a collection, by the kind of thing.
_IN_COLLECTION = {
    "collection_id": "collection",
    "project_id": "project",
    "node_id": "node",
    "edge_id": "edge",
    "job_id": "job",
    "material_id": "material",
    "message_id": "message",
    "workflow_id": "workflow",
}


@dataclass(frozen=True)
class Access:
    """What the path of a request points into, and the caller's role there."""

    collection_id: str
    project_id: str | None
    role: Role


def no_edit_lock(endpoint):
    """Mark a route that changes a project without needing its lock (the
    lock routes themselves; the owner deleting a project)."""
    endpoint.no_edit_lock = True
    return endpoint


def _not_found(kind: str, value: str) -> ApiError:
    what = kind.replace("_", " ")
    return ApiError(404, ErrorCode.not_found, f"{what} {value} not found", {"id": value})


async def authorize(request: Request, user: UserDep) -> None:
    """Every ID in the path must be in a collection the caller is a member
    of; anything else is "not found", so IDs from other collections reveal
    nothing. A change to a project also needs its lock (this tab's, see
    ``EDIT_SESSION_HEADER``): 409 ``project_locked`` otherwise."""
    store: Store = request.app.state.store
    collection = project = None
    first = None
    for param, value in request.path_params.items():
        kind = _IN_COLLECTION.get(param)
        if param == "asset_id" and request.url.path.startswith("/api/collection-assets/"):
            kind = "collection_asset"
        if kind is None or not _WELL_FORMED.match(value):
            continue  # a malformed ID: the route's own validation answers (422)
        found_collection, found_project = await run_in_threadpool(store.locate, kind, value)
        if collection is not None and found_collection != collection:
            raise _not_found(kind, value)
        collection, project = found_collection, found_project or project
        first = first or (kind, value)
    if collection is None:
        return
    role = await run_in_threadpool(store.role_in, collection, user.id)
    if role is None:
        raise _not_found(*first)
    request.state.access = Access(collection, project, role)
    endpoint = request.scope.get("endpoint")
    if (
        project is not None
        and request.method not in ("GET", "HEAD")
        and not getattr(endpoint, "no_edit_lock", False)
    ):
        session = request.headers.get(EDIT_SESSION_HEADER)
        await run_in_threadpool(store.acquire_lock, project, user.id, session)


def _access(request: Request) -> Access:
    access = getattr(request.state, "access", None)
    if access is None:  # every route using this has a collection in its path
        raise RuntimeError("no collection in this route's path")
    return access


AccessDep = Annotated[Access, Depends(_access)]


def require_owner(access: AccessDep) -> None:
    """For owner-only routes: 403 ``forbidden`` for editors."""
    if access.role != Role.owner:
        raise ApiError(403, ErrorCode.forbidden, "only the collection's owner can do this")
