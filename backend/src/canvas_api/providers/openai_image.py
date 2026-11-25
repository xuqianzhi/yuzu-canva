"""OpenAI Images API.

- No reference images: text -> image, ``POST /images/generations`` (JSON).
- One or more reference images: ``POST /images/edits`` (multipart, one
  ``image[]`` part per reference, in reference order). Mentions in the prompt
  become "image 1", "image 2", ... so the prompt can say which is which.
- Reference images are compressed first, like every provider's
  (``RefFile.load``: JPEG, long edge <= 1024 px, quality 80).
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from ..contract import ImageParams, MediaKind
from ..domain.workflow import image_label
from .base import GenerationRequest, GenerationResult, ProviderError, label_mentions, reason
from .media import sniff_image

# OpenAI's limit for GPT Image models on /images/edits.
MAX_EDIT_IMAGES = 16


class OpenAIImageGenerator:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout = httpx.Timeout(timeout_s, connect=15)
        self._transport = transport

    async def run(self, request: GenerationRequest) -> GenerationResult:
        if not self._api_key:
            raise ProviderError("OPENAI_API_KEY is not set on the backend")
        params = request.params
        if not isinstance(params, ImageParams):
            raise ProviderError(f"expected image params, got {params.kind}")

        images = [f for f in request.files if f.kind == MediaKind.image]
        if len(images) > MAX_EDIT_IMAGES:
            raise ProviderError(f"OpenAI accepts at most {MAX_EDIT_IMAGES} reference images")
        fields: dict[str, Any] = {
            "model": self._model,
            "n": 1,
            "size": params.size,
            "quality": params.quality,
        }
        if images:
            fields["prompt"] = label_mentions(
                request.prompt, images, lambda n: image_label(n, request.prompt)
            )
            payloads = [f.load() for f in images]
            parts = [("image[]", (p.filename, p.data, p.mime)) for p in payloads]
            response = await self._post(
                "/images/edits",
                data={k: str(v) for k, v in fields.items()},
                files=parts,
            )
        else:
            fields["prompt"] = request.prompt
            response = await self._post("/images/generations", json=fields)

        try:
            b64 = response.json()["data"][0]["b64_json"]
            data = base64.b64decode(b64)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("OpenAI returned no image") from exc

        mime, ext, width, height = sniff_image(data)
        return GenerationResult(
            kind=MediaKind.image, data=data, mime=mime, ext=ext, width=width, height=height
        )

    async def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}{path}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    **kwargs,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("OpenAI did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not reach OpenAI: {reason(exc)}") from exc
        if response.status_code >= 400:
            raise ProviderError(f"OpenAI {response.status_code}: {_error_message(response)}")
        return response


def _error_message(response: httpx.Response) -> str:
    try:
        message = response.json()["error"]["message"]
        if message:
            return str(message)
    except (ValueError, KeyError, TypeError):
        pass
    return response.text[:300] or response.reason_phrase
