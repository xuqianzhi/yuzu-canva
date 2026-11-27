"""Settings from the environment. Empty values mean "use the default"."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _flag(name: str) -> bool:
    return _env(name, "0").lower() in ("1", "true", "yes")


def _emails(raw: str) -> frozenset[str]:
    return frozenset(e.strip().lower() for e in raw.replace(";", ",").split(",") if e.strip())


# Local development: the compose `db` service (never your Supabase database).
LOCAL_DATABASE_URL = "postgresql://canvas:canvas@127.0.0.1:5433/canvas"


@dataclass(frozen=True)
class Limits:
    """What one user may spend. Counted per UTC day; 0 means no limit."""

    text_per_day: int = 200
    images_per_day: int = 50
    videos_per_day: int = 10
    # Jobs queued or running at once (more are refused, not queued).
    active_jobs: int = 30
    # Text-model calls (running a step, an AI edit) per minute.
    text_per_minute: int = 10


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    openai_api_key: str
    openai_base_url: str
    openai_image_model: str
    openai_timeout_s: float
    # Jobs that may run at once across all providers.
    worker_concurrency: int
    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    seedance_model: str = "doubao-seedance-2-0-fast-260128"
    seedance_poll_interval_s: float = 10
    seedance_poll_timeout_s: float = 1800
    # How long one Ark request may take. Creating a task sends every
    # reference inline, and from outside China the route to Beijing can run
    # at a few KB/s, so a request of a couple of MB takes minutes (matches
    # seedance-ui's default).
    seedance_http_timeout_s: float = 900
    # Replace real providers with offline fakes (for UI work).
    fake_generators: bool = False
    # Text steps and AI edits.
    openai_text_model: str = "gpt-5-mini"

    # --- data -------------------------------------------------------------------
    # Postgres. Locally the compose `db` service; in production Supabase.
    database_url: str = LOCAL_DATABASE_URL
    # Where media lives: "local" (data_dir/assets, data_dir/global) or "gcs"
    # (the bucket below, e.g. Cloud Storage for Firebase's default bucket).
    storage: str = "local"
    bucket: str = ""
    # Signs media links (/api/assets/<id>/content?e=…&s=…), so <img> and
    # <video> tags work without a sign-in header. Keep it stable: changing it
    # breaks links already handed out (a page reload fixes them).
    url_secret: str = ""

    # --- sign-in ----------------------------------------------------------------
    # Firebase project whose ID tokens are accepted ("" turns Firebase off).
    firebase_project_id: str = ""
    # Accept "Bearer dev:<email>" tokens. Local development and tests only;
    # refused on Cloud Run.
    dev_auth: bool = False
    # Who may sign in (lowercase emails). Empty: nobody with Firebase sign-in;
    # anybody with dev sign-in.
    allowed_emails: frozenset[str] = field(default_factory=frozenset)

    # --- spending ---------------------------------------------------------------
    limits: Limits = field(default_factory=Limits)
    # Turns every model call off at once (503), e.g. while costs look wrong.
    generation_off: bool = False

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(_env("CANVAS_DATA_DIR", "./data")),
            openai_api_key=_env("OPENAI_API_KEY", ""),
            openai_base_url=_env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_image_model=_env("OPENAI_IMAGE_MODEL", "gpt-image-2"),
            openai_timeout_s=float(_env("OPENAI_TIMEOUT_S", "300")),
            worker_concurrency=int(_env("CANVAS_WORKER_CONCURRENCY", "4")),
            ark_api_key=_env("ARK_API_KEY", ""),
            ark_base_url=_env("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            seedance_model=_env("SEEDANCE_MODEL", "doubao-seedance-2-0-fast-260128"),
            seedance_poll_interval_s=float(_env("SEEDANCE_POLL_INTERVAL", "10")),
            seedance_poll_timeout_s=float(_env("SEEDANCE_POLL_TIMEOUT", "1800")),
            seedance_http_timeout_s=float(_env("SEEDANCE_HTTP_TIMEOUT", "900")),
            fake_generators=_flag("CANVAS_FAKE_GENERATORS"),
            openai_text_model=_env("OPENAI_TEXT_MODEL", "gpt-5-mini"),
            database_url=_env("DATABASE_URL", LOCAL_DATABASE_URL),
            storage=_env("CANVAS_STORAGE", "local").lower(),
            bucket=_env("CANVAS_BUCKET", ""),
            url_secret=_env("CANVAS_URL_SECRET", ""),
            firebase_project_id=_env("FIREBASE_PROJECT_ID", ""),
            dev_auth=_flag("CANVAS_DEV_AUTH"),
            allowed_emails=_emails(_env("CANVAS_ALLOWED_EMAILS", "")),
            limits=Limits(
                text_per_day=int(_env("CANVAS_LIMIT_TEXT_PER_DAY", "200")),
                images_per_day=int(_env("CANVAS_LIMIT_IMAGES_PER_DAY", "50")),
                videos_per_day=int(_env("CANVAS_LIMIT_VIDEOS_PER_DAY", "10")),
                active_jobs=int(_env("CANVAS_LIMIT_ACTIVE_JOBS", "30")),
                text_per_minute=int(_env("CANVAS_LIMIT_TEXT_PER_MINUTE", "10")),
            ),
            generation_off=_flag("CANVAS_GENERATION_OFF"),
        )

    def check(self) -> None:
        """Refuse settings that would run unsafely."""
        on_cloud_run = bool(os.environ.get("K_SERVICE"))
        if self.dev_auth and on_cloud_run:
            raise RuntimeError("CANVAS_DEV_AUTH must not be set on Cloud Run")
        if not self.dev_auth and not self.firebase_project_id:
            raise RuntimeError("set FIREBASE_PROJECT_ID (or CANVAS_DEV_AUTH=1 for local work)")
        if self.storage not in ("local", "gcs"):
            raise RuntimeError("CANVAS_STORAGE must be 'local' or 'gcs'")
        if self.storage == "gcs" and not self.bucket:
            raise RuntimeError("CANVAS_STORAGE=gcs needs CANVAS_BUCKET")
        if on_cloud_run and len(self.url_secret) < 32:
            raise RuntimeError("CANVAS_URL_SECRET must be set (32+ characters) on Cloud Run")
