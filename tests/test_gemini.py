from __future__ import annotations

import json

import httpx
import pytest

from nextorca.gemini import GeminiProvider
from nextorca.provider import ProviderError, ProviderUnavailableError


def _tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to read"}
                    },
                    "required": ["file_path"],
                    "additionalProperties": False,
                },
            },
        }
    ]


def test_gemini_generate_content_maps_messages_tools_and_function_results():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {"text": "I will inspect that."},
                                {"functionCall": {"name": "Read", "args": {"file_path": "README.md"}}},
                            ],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 44, "candidatesTokenCount": 11},
            },
        )

    provider = GeminiProvider(api_key="gemini-test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.complete(
        model="gemini-test-model",
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
        tools=_tools(),
    )

    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-test-model:generateContent"
    )
    headers = captured["headers"]
    assert headers["x-goog-api-key"] == "gemini-test-key"
    body = captured["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "System policy"
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "Read"
    assert declaration["parameters"]["type"] == "OBJECT"
    assert declaration["parameters"]["properties"]["file_path"]["type"] == "STRING"
    assert "additionalProperties" not in declaration["parameters"]
    assert body["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
    assert body["contents"][1]["role"] == "model"
    assert body["contents"][1]["parts"][1]["functionCall"]["args"] == {"file_path": "README.md"}
    assert body["contents"][2]["parts"][0]["functionResponse"]["name"] == "Read"
    assert result.content == "I will inspect that."
    assert result.tool_calls[0].name == "Read"
    assert result.tool_calls[0].arguments == {"file_path": "README.md"}
    assert result.finish_reason == "STOP"
    assert result.usage == {"input_tokens": 44, "output_tokens": 11}


def test_gemini_accepts_custom_base_url_and_models_prefix():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    provider = GeminiProvider(
        "https://proxy.example/",
        api_key="key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.complete(
        model="models/gemini-test",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
    )

    assert captured["url"] == "https://proxy.example/v1beta/models/gemini-test:generateContent"
    assert result.content == "ok"


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_gemini_transient_http_errors_are_unavailable(status: int):
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(status)))
    provider = GeminiProvider(api_key="key", client=client)
    with pytest.raises(ProviderUnavailableError, match=f"HTTP {status}"):
        provider.complete(model="gemini-test", messages=[{"role": "user", "content": "hi"}], tools=[])


def test_gemini_client_http_errors_are_provider_errors():
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(400)))
    provider = GeminiProvider(api_key="key", client=client)
    with pytest.raises(ProviderError, match="HTTP 400"):
        provider.complete(model="gemini-test", messages=[{"role": "user", "content": "hi"}], tools=[])


def test_gemini_requires_api_key():
    provider = GeminiProvider()
    with pytest.raises(ProviderError, match="API key is required"):
        provider.complete(model="gemini-test", messages=[{"role": "user", "content": "hi"}], tools=[])


def test_gemini_rejects_unknown_function_calls():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "candidates": [
                        {"content": {"parts": [{"functionCall": {"name": "Shell", "args": {}}}]}}
                    ]
                },
            )
        )
    )
    provider = GeminiProvider(api_key="key", client=client)
    with pytest.raises(ProviderError, match="did not provide"):
        provider.complete(model="gemini-test", messages=[{"role": "user", "content": "hi"}], tools=_tools())


def test_gemini_rejects_tool_results_without_matching_call():
    with pytest.raises(ProviderError, match="does not match"):
        GeminiProvider._convert_messages([{"role": "tool", "tool_call_id": "missing", "content": "result"}])
