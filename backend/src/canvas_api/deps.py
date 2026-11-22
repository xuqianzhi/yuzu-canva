"""Shared objects for routes, created by the app lifespan."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from .jobs.worker import Worker
from .providers.openai_text import TextModel
from .store import Store


def _store(request: Request) -> Store:
    return request.app.state.store


def _worker(request: Request) -> Worker:
    return request.app.state.worker


def _text_model(request: Request) -> TextModel:
    return request.app.state.text_model


StoreDep = Annotated[Store, Depends(_store)]
TextModelDep = Annotated[TextModel, Depends(_text_model)]
WorkerDep = Annotated[Worker, Depends(_worker)]


def remove_files(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
