from __future__ import annotations

import json

import httpx
import pytest

from nextorca.anthropic import AnthropicMessagesProvider
from nextorca.provider import ProviderError, ProviderUnavailableError


def test_anthropic_messages_request_maps_system_tools_and_tool_results():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "I will inspect that."},
                    {"type": "tool_use", "id": "toolu_123", "name": "Read", "input": {"file_path": "README.md"}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 41, "output_tokens": 12},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = AnthropicMessagesProvider(api_key="anthropic-test-key", client=client)
    result = provider.complete(
        model="claude-test-model",
        messages=[
            {"role": "system", "content": "System policy"},
            {"role": "user", "content": "Read README"},
            {
                "role": "assistant",
                "content": "Reading",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "Read", "arguments": '{"file_path":"README.md"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "file contents"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "Read",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}},
                },
            }
        ],
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    headers = captured["headers"]
    assert headers["x-api-key"] == "anthropic-test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    body = captured["body"]
    assert body["model"] == "claude-test-model"
    assert body["max_tokens"] == 8192
    assert body["system"] == "System policy"
    assert body["tools"][0]["input_schema"]["type"] == "object"
    assert body["tool_choice"] == {"type": "auto"}
    assert body["messages"][1]["content"][1] == {
        "type": "tool_use", "id": "call-1", "name": "Read", "input": {"file_path": "README.md"}
    }
    assert body["messages"][2]["content"][0] == {
        "type": "tool_result", "tool_use_id": "call-1", "content": "file contents"
    }
    assert result.content == "I will inspect that."
    assert result.tool_calls[0].id == "toolu_123"
    assert result.tool_calls[0].arguments == {"file_path": "README.md"}
    assert result.finish_reason == "tool_use"
    assert result.usage == {"input_tokens": 41, "output_tokens": 12}


def test_anthropic_accepts_base_url_with_v1_suffix_and_without_api_key():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "usage": {}})

    provider = AnthropicMessagesProvider("https://proxy.example/v1/", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.complete(model="claude-test", messages=[{"role": "user", "content": "hi"}], tools=[]).content == "ok"
    assert captured["url"] == "https://proxy.example/v1/messages"
    assert "x-api-key" not in captured["headers"]


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_anthropic_transient_http_errors_are_unavailable(status: int):
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(status)))
    provider = AnthropicMessagesProvider(client=client)
    with pytest.raises(ProviderUnavailableError, match=f"HTTP {status}"):
        provider.complete(model="claude-test", messages=[{"role": "user", "content": "hi"}], tools=[])


def test_anthropic_client_http_errors_are_provider_errors():
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(401)))
    provider = AnthropicMessagesProvider(client=client)
    with pytest.raises(ProviderError, match="HTTP 401"):
        provider.complete(model="claude-test", messages=[{"role": "user", "content": "hi"}], tools=[])


def test_anthropic_rejects_invalid_tool_history():
    with pytest.raises(ProviderError, match="invalid tool call"):
        AnthropicMessagesProvider._convert_messages([
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "function": {"name": "Read", "arguments": "[]"}}]}
        ])
