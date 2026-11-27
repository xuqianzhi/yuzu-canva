"""The OpenAI text model against a mocked HTTP transport."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from canvas_api.domain.workflow import run_spec
from canvas_api.providers.base import ProviderError, RefPayload
from canvas_api.providers.openai_text import OpenAITextModel


def model(handler) -> OpenAITextModel:
    return OpenAITextModel(
        api_key="sk-test",
        base_url="https://openai.test/v1",
        model="gpt-test",
        timeout_s=5,
        transport=httpx.MockTransport(handler),
    )


def answer(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_structured_request_with_images():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return answer('{"items": []}')

    image = RefPayload(data=b"JPEG", mime="image/jpeg", filename="a.jpg")
    text = asyncio.run(
        model(handler).complete(
            "be brief",
            [{"role": "user", "content": "write it"}],
            run_spec(5),
            [image],
        )
    )
    assert text == '{"items": []}'
    assert seen["url"] == "https://openai.test/v1/chat/completions"
    body = seen["body"]
    assert body["model"] == "gpt-test"
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    parts = body["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "write it"}
    assert parts[1]["image_url"]["url"] == "data:image/jpeg;base64,SlBFRw=="
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["required"] == ["items"]
    assert fmt["json_schema"]["schema"]["properties"]["items"]["maxItems"] == 5


def test_plain_text_has_no_response_format():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return answer("hello")

    asyncio.run(model(handler).complete("s", [{"role": "user", "content": "hi"}]))
    assert "response_format" not in bodies[0]


def test_errors_are_provider_errors():
    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": None, "refusal": "no"}}]}
        )

    with pytest.raises(ProviderError, match="refused"):
        asyncio.run(model(refused).complete("s", [{"role": "user", "content": "x"}]))

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad model"}})

    with pytest.raises(ProviderError, match="bad model"):
        asyncio.run(model(failing).complete("s", [{"role": "user", "content": "x"}]))
