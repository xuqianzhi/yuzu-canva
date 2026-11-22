"""FastAPI application: routes under /api, contract-shaped errors."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import TypeAdapter

from . import __version__, errors
from .config import Settings
from .contract import Operation, ServerEvent
from .deps import remove_files
from .jobs.worker import Worker
from .providers.base import Generator
from .providers.fake import FakeImageGenerator, FakeTextModel, FakeVideoGenerator
from .providers.openai_image import OpenAIImageGenerator
from .providers.openai_text import OpenAITextModel, TextGenerator, TextModel
from .providers.seedance_video import SeedanceVideoGenerator
from .routes import (
    assets,
    edges,
    events,
    global_assets,
    health,
    instructions,
    jobs,
    materials,
    nodes,
    projects,
    workflow,
)
from .store import Store

API_PREFIX = "/api"


def _openapi(app: FastAPI) -> dict[str, Any]:
    """OpenAPI schema, plus the WebSocket event types OpenAPI can't express."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, description=app.description, routes=app.routes
    )
    ref = "#/components/schemas/{model}"
    event_schema = TypeAdapter(ServerEvent).json_schema(ref_template=ref, mode="serialization")
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, definition in event_schema.pop("$defs", {}).items():
        components.setdefault(name, definition)
    components["ServerEvent"] = event_schema
    app.openapi_schema = schema
    return schema


def default_text_model(settings: Settings) -> TextModel:
    if settings.fake_generators:
        return FakeTextModel(delay_s=1.0)
    return OpenAITextModel(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_text_model,
        timeout_s=settings.openai_timeout_s,
    )


def default_generators(settings: Settings, text_model: TextModel) -> dict[Operation, Generator]:
    if settings.fake_generators:
        fake = FakeImageGenerator()
        return {
            Operation.text_generate: TextGenerator(text_model),
            Operation.image_generate: fake,
            Operation.image_edit: fake,
            Operation.video_generate: FakeVideoGenerator(),
        }
    openai_image = OpenAIImageGenerator(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_image_model,
        timeout_s=settings.openai_timeout_s,
    )
    seedance = SeedanceVideoGenerator(
        api_key=settings.ark_api_key,
        base_url=settings.ark_base_url,
        model=settings.seedance_model,
        poll_interval_s=settings.seedance_poll_interval_s,
        poll_timeout_s=settings.seedance_poll_timeout_s,
        http_timeout_s=settings.seedance_http_timeout_s,
    )
    return {
        Operation.text_generate: TextGenerator(text_model),
        Operation.image_generate: openai_image,
        Operation.image_edit: openai_image,
        Operation.video_generate: seedance,
    }


def create_app(
    settings: Settings | None = None,
    generators: dict[Operation, Generator] | None = None,
    text_model: TextModel | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own settings, fake generators and a
    fake text model (used for text jobs too, unless `generators` has one)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved = settings or Settings.from_env()
        store = Store(resolved.db_path, resolved.assets_dir)
        model = text_model if text_model is not None else default_text_model(resolved)
        if generators is not None:
            ops = {Operation.text_generate: TextGenerator(model), **generators}
        else:
            ops = default_generators(resolved, model)
        worker = Worker(store, ops, concurrency=resolved.worker_concurrency)
        app.state.store, app.state.worker, app.state.text_model = store, worker, model
        # Deletes are soft (for undo); erase what has been deleted a while.
        remove_files(store.purge_deleted())
        # Links follow prompts; make sure they do after any migration.
        store.sync_all_links()
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()
            store.close()

    app = FastAPI(
        lifespan=lifespan,
        title="seedance-canvas API",
        version=__version__,
        description=(
            "Canvas of generation nodes. A node turns a prompt (plus the outputs of "
            "the nodes it references) into text, an image or a video."
        ),
        # Split input/output schemas would generate Node and Node-Input types;
        # one schema per model keeps the TypeScript names clean.
        separate_input_output_schemas=False,
    )
    errors.install(app)
    modules = (
        health,
        projects,
        nodes,
        edges,
        jobs,
        materials,
        global_assets,
        instructions,
        workflow,
        assets,
        events,
    )
    for module in modules:
        app.include_router(module.router, prefix=API_PREFIX)
    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()
