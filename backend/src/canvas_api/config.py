"""Settings from the environment. Empty values mean "use the default"."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


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
    # Text steps and node chat.
    openai_text_model: str = "gpt-5-mini"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "canvas.db"

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
            fake_generators=_env("CANVAS_FAKE_GENERATORS", "0").lower() in ("1", "true", "yes"),
            openai_text_model=_env("OPENAI_TEXT_MODEL", "gpt-5-mini"),
        )
