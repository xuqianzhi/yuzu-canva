"""Shared objects for routes, created by the app lifespan; and who's calling."""

from __future__ import annotations

import re
import time
from typing import Annotated

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool

from .auth import Authenticator, User
from .config import Settings
from .contract import ErrorCode
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

# Path parameters that name something a user owns, by the kind of thing.
_OWNED = {
    "project_id": "project",
    "node_id": "node",
    "edge_id": "edge",
    "job_id": "job",
    "material_id": "material",
    "message_id": "message",
    "template_id": "template",
}


async def authorize(request: Request, user: UserDep) -> None:
    """Every ID in the path must belong to the caller; anything else is
    "not found", so IDs from other accounts reveal nothing."""
    store: Store = request.app.state.store
    for param, value in request.path_params.items():
        kind = _OWNED.get(param)
        if param == "asset_id" and request.url.path.startswith("/api/global-assets/"):
            kind = "global_asset"
        if kind is None or not _WELL_FORMED.match(value):
            continue  # a malformed ID: the route's own validation answers (422)
        owner = await run_in_threadpool(store.owner_of, kind, value)
        if owner != user.id:
            what = kind.replace("_", " ")
            raise ApiError(404, ErrorCode.not_found, f"{what} {value} not found", {"id": value})
