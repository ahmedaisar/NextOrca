from __future__ import annotations

import json

import httpx
import pytest

from nextorca.openai_compatible import OpenAICompatibleProvider
from nextorca.provider import ProviderError


def test_openai_compatible_provider_parses_text_and_tool_calls():
    request_json = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_json
        request_json = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "Searching",
                            "tool_calls": [
                                {
                                    "id": "call-123",
                                    "type": "function",
                                    "function": {
                                        "name": "Read",
                                        "arguments": '{"file_path":"README.md"}',
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        "http://model.test/v1",
        api_key="test-key",
        client=client,
    )

    result = provider.complete(
        model="mock-model",
        messages=[{"role": "user", "content": "Read README"}],
        tools=[{"type": "function", "function": {"name": "Read"}}],
    )

    assert request_json["model"] == "mock-model"
    assert request_json["tool_choice"] == "auto"
    assert result.content == "Searching"
    assert result.tool_calls[0].name == "Read"
    assert result.tool_calls[0].arguments == {"file_path": "README.md"}


def test_provider_rejects_non_object_tool_arguments():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "bad",
                                        "function": {
                                            "name": "Read",
                                            "arguments": '["not", "object"]',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )
        )
    )
    provider = OpenAICompatibleProvider("http://model.test/v1", client=client)
    with pytest.raises(ProviderError, match="invalid tool call"):
        provider.complete(model="test", messages=[], tools=[])


def test_provider_surfaces_http_status_without_response_body():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(429, json={"error": "rate limited"})
        )
    )
    provider = OpenAICompatibleProvider("http://model.test/v1", client=client)
    with pytest.raises(ProviderError, match="HTTP 429"):
        provider.complete(model="test", messages=[], tools=[])
