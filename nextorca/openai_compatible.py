from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from nextorca.provider import ProviderError, ProviderUnavailableError
from nextorca.types import AssistantTurn, ProviderStreamChunk, ToolCall


class OpenAICompatibleProvider:
    """Adapter for OpenAI Chat Completions-compatible local or hosted endpoints."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("A provider base URL is required.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        normalized = base_url.rstrip("/")
        self.endpoint = (
            normalized
            if normalized.endswith("/chat/completions")
            else f"{normalized}/chat/completions"
        )
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
        )

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self._client.post(
                self.endpoint,
                json=body,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Model provider request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            error_type = ProviderUnavailableError if status in {408, 429} or status >= 500 else ProviderError
            raise error_type(f"Model provider returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("Model provider connection failed.") from exc
        except ValueError as exc:
            raise ProviderError("Model provider returned invalid JSON.") from exc

        try:
            choice = payload["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Model provider returned an invalid response shape.") from exc

        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ProviderError("Model provider returned non-text message content.")

        calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            try:
                function = item["function"]
                arguments = function["arguments"]
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise TypeError("arguments must be an object")
                name = function["name"]
                call_id = item.get("id") or f"call_{len(calls) + 1}"
                if not isinstance(name, str) or not name:
                    raise TypeError("tool name must be a non-empty string")
                calls.append(ToolCall(id=str(call_id), name=name, arguments=arguments))
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ProviderError("Model provider returned an invalid tool call.") from exc

        raw_usage = payload.get("usage") or {}
        usage: dict[str, int] = {}
        if isinstance(raw_usage, dict):
            for target, candidates in {
                "input_tokens": ("prompt_tokens", "input_tokens"),
                "output_tokens": ("completion_tokens", "output_tokens"),
            }.items():
                for candidate in candidates:
                    value = raw_usage.get(candidate)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        usage[target] = value
                        break

        return AssistantTurn(
            content=content,
            tool_calls=tuple(calls),
            finish_reason=choice.get("finish_reason"),
            usage=usage,
        )


    def stream_complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[ProviderStreamChunk]:
        """Stream Chat Completions text/tool-call deltas and finish with one normalized turn."""
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        content_parts: list[str] = []
        tool_parts: dict[int, dict[str, str]] = {}
        usage: dict[str, int] = {}
        finish_reason: str | None = None
        try:
            with self._client.stream(
                "POST", self.endpoint, json=body, headers=headers,
                timeout=self.timeout_seconds,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderError("Model provider returned invalid streaming JSON.") from exc
                    if not isinstance(payload, dict):
                        raise ProviderError("Model provider returned an invalid streaming event.")

                    raw_usage = payload.get("usage")
                    if isinstance(raw_usage, dict):
                        for target, candidates in {
                            "input_tokens": ("prompt_tokens", "input_tokens"),
                            "output_tokens": ("completion_tokens", "output_tokens"),
                        }.items():
                            for candidate in candidates:
                                value = raw_usage.get(candidate)
                                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                                    usage[target] = value
                                    break

                    choices = payload.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    finish_reason = choice.get("finish_reason") or finish_reason
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content is not None:
                        if not isinstance(content, str):
                            raise ProviderError("Streaming provider returned non-text content.")
                        if content:
                            content_parts.append(content)
                            yield ProviderStreamChunk(content_delta=content)

                    for item in delta.get("tool_calls") or []:
                        index = item.get("index", 0)
                        if not isinstance(index, int) or index < 0:
                            raise ProviderError("Streaming provider returned an invalid tool-call index.")
                        entry = tool_parts.setdefault(
                            index, {"id": "", "name": "", "arguments": ""}
                        )
                        call_id = item.get("id")
                        if isinstance(call_id, str) and call_id:
                            entry["id"] = call_id
                        function = item.get("function") or {}
                        name_delta = function.get("name")
                        arguments_delta = function.get("arguments")
                        if name_delta is not None:
                            if not isinstance(name_delta, str):
                                raise ProviderError("Streaming provider returned an invalid tool name.")
                            entry["name"] += name_delta
                        if arguments_delta is not None:
                            if not isinstance(arguments_delta, str):
                                raise ProviderError("Streaming provider returned invalid tool arguments.")
                            entry["arguments"] += arguments_delta
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Model provider stream timed out.") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            error_type = (
                ProviderUnavailableError
                if status in {408, 429} or status >= 500
                else ProviderError
            )
            raise error_type(f"Model provider returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("Model provider stream connection failed.") from exc

        calls: list[ToolCall] = []
        for index, item in sorted(tool_parts.items()):
            try:
                arguments = json.loads(item["arguments"] or "{}")
                if not isinstance(arguments, dict) or not item["name"]:
                    raise TypeError("tool name and object arguments are required")
                calls.append(
                    ToolCall(
                        id=item["id"] or f"call_{index + 1}",
                        name=item["name"],
                        arguments=arguments,
                    )
                )
            except (TypeError, json.JSONDecodeError) as exc:
                raise ProviderError("Model provider returned an invalid streamed tool call.") from exc

        yield ProviderStreamChunk(
            final_turn=AssistantTurn(
                content="".join(content_parts),
                tool_calls=tuple(calls),
                finish_reason=finish_reason,
                usage=usage,
            )
        )
