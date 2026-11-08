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
                ],
                "usage": {"prompt_tokens": 31, "completion_tokens": 9},
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
    assert result.usage == {"input_tokens": 31, "output_tokens": 9}


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

def test_openai_compatible_provider_streams_text_and_tool_calls():
    request_json = {}
    events = [
        {"choices": [{"delta": {"content": "Inspecting "}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call-stream-1", "function": {
                "name": "Read", "arguments": '{"file_path":'
            }}
        ]}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '"README.md"}'}}
        ]}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 4}},
    ]
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_json
        request_json = json.loads(request.content)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    provider = OpenAICompatibleProvider(
        "http://model.test/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    chunks = list(provider.stream_complete(
        model="mock",
        messages=[{"role": "user", "content": "Read README"}],
        tools=[{"type": "function", "function": {"name": "Read"}}],
    ))

    assert request_json["stream"] is True
    assert [chunk.content_delta for chunk in chunks if chunk.content_delta] == ["Inspecting "]
    final = chunks[-1].final_turn
    assert final is not None
    assert final.content == "Inspecting "
    assert final.tool_calls[0].name == "Read"
    assert final.tool_calls[0].arguments == {"file_path": "README.md"}
    assert final.usage == {"input_tokens": 12, "output_tokens": 4}


def test_openai_compatible_provider_rejects_malformed_streamed_tool_arguments():
    body = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"bad",'
        '"function":{"name":"Read","arguments":"not-json"}}]},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    provider = OpenAICompatibleProvider(
        "http://model.test/v1",
        client=httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, text=body)
        )),
    )
    with pytest.raises(ProviderError, match="invalid streamed tool call"):
        list(provider.stream_complete(model="mock", messages=[], tools=[]))
