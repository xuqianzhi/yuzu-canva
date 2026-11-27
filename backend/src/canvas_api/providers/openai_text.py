"""OpenAI text: Chat Completions, optionally with a JSON-schema answer.

``TextModel`` is the small interface the rest of the backend uses (the
text job generator and AI edits); ``OpenAITextModel`` implements it
over ``POST /chat/completions``. Reference images go along as data URLs
(compressed like every reference, see ``RefFile.load``).
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

import httpx

from ..contract import MediaKind
from ..domain.workflow import OutputSpec, W, image_label
from .base import (
    GenerationRequest,
    GenerationResult,
    ProviderError,
    RefPayload,
    label_mentions,
    reason,
)


class TextModel(Protocol):
    async def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        spec: OutputSpec | None = None,
        images: list[RefPayload] | None = None,
    ) -> str:
        """The model's answer. `messages` alternate {"role": "user" |
        "assistant", "content": text}, ending with the user's; images go
        with the first user message. With a schema, the answer is its JSON."""
        ...


class OpenAITextModel:
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

    async def complete(
        self,
        system: str,
        messages: list[dict[str, str]],
        spec: OutputSpec | None = None,
        images: list[RefPayload] | None = None,
    ) -> str:
        if not self._api_key:
            raise ProviderError("OPENAI_API_KEY is not set on the backend")
        chat: list[dict[str, Any]] = [{"role": "system", "content": system}]
        attached = False
        for message in messages:
            content: Any = message["content"]
            if images and not attached and message["role"] == "user":
                content = [{"type": "text", "text": content}] + [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{p.mime};base64,{base64.b64encode(p.data).decode()}"
                        },
                    }
                    for p in images
                ]
                attached = True
            chat.append({"role": message["role"], "content": content})
        body: dict[str, Any] = {"model": self._model, "messages": chat}
        if spec is not None and spec.schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": spec.name, "strict": True, "schema": spec.schema},
            }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("OpenAI did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not reach OpenAI: {reason(exc)}") from exc
        if response.status_code >= 400:
            raise ProviderError(f"OpenAI {response.status_code}: {_error_message(response)}")
        try:
            message = response.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("OpenAI returned no answer") from exc
        if message.get("refusal"):
            raise ProviderError(f"OpenAI refused: {message['refusal']}")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("OpenAI returned an empty answer")
        return content


class TextGenerator:
    """Runs text jobs: the job's system prompt and prompt, its format."""

    def __init__(self, model: TextModel) -> None:
        self._model = model

    async def run(self, request: GenerationRequest) -> GenerationResult:
        files = [f for f in request.files if f.kind == MediaKind.image]
        images = [f.load() for f in files]
        prompt = label_mentions(request.prompt, files, lambda n: image_label(n, request.prompt))
        answer = await self._model.complete(
            request.system or W["plain"],
            [{"role": "user", "content": prompt}],
            None,
            images,
        )
        return GenerationResult(kind=MediaKind.text, text=answer.strip())


def _error_message(response: httpx.Response) -> str:
    try:
        message = response.json()["error"]["message"]
        if message:
            return str(message)
    except (ValueError, KeyError, TypeError):
        pass
    return response.text[:300] or response.reason_phrase
