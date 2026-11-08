from __future__ import annotations

import json
from typing import Any

import httpx

from nextorca.provider import ProviderError, ProviderUnavailableError
from nextorca.types import AssistantTurn, ToolCall


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
