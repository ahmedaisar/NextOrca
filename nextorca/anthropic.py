from __future__ import annotations

import json
from typing import Any

import httpx

from nextorca.provider import ProviderError, ProviderUnavailableError
from nextorca.types import AssistantTurn, ToolCall


ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_MAX_TOKENS = 8192


class AnthropicMessagesProvider:
    """Native adapter for Anthropic's Messages API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client: httpx.Client | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive.")
        normalized = (base_url or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
        if normalized.endswith("/v1/messages"):
            self.endpoint = normalized
        elif normalized.endswith("/v1"):
            self.endpoint = f"{normalized}/messages"
        else:
            self.endpoint = f"{normalized}/v1/messages"
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
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
        if not model or not model.strip():
            raise ProviderError("An Anthropic model identifier is required.")
        system, conversation = self._convert_messages(messages)
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": conversation,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = self._convert_tools(tools)
            body["tool_choice"] = {"type": "auto"}

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_API_VERSION,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

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
            raise ProviderUnavailableError("Anthropic request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            error_type = ProviderUnavailableError if status in {408, 429} or status >= 500 else ProviderError
            raise error_type(f"Anthropic returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("Anthropic connection failed.") from exc
        except ValueError as exc:
            raise ProviderError("Anthropic returned invalid JSON.") from exc

        try:
            blocks = payload["content"]
            if not isinstance(blocks, list):
                raise TypeError("content must be a list")
            text_parts: list[str] = []
            calls: list[ToolCall] = []
            for block in blocks:
                if not isinstance(block, dict):
                    raise TypeError("content block must be an object")
                block_type = block.get("type")
                if block_type == "text":
                    text = block.get("text", "")
                    if not isinstance(text, str):
                        raise TypeError("text block must contain text")
                    text_parts.append(text)
                elif block_type == "tool_use":
                    name = block.get("name")
                    call_id = block.get("id")
                    arguments = block.get("input")
                    if not isinstance(name, str) or not name:
                        raise TypeError("tool name must be a non-empty string")
                    if not isinstance(call_id, str) or not call_id:
                        raise TypeError("tool use id must be a non-empty string")
                    if not isinstance(arguments, dict):
                        raise TypeError("tool input must be an object")
                    calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
            raw_usage = payload.get("usage") or {}
            usage: dict[str, int] = {}
            if isinstance(raw_usage, dict):
                for source, target in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens")):
                    value = raw_usage.get(source)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        usage[target] = value
            stop_reason = payload.get("stop_reason")
            return AssistantTurn(
                content="\n".join(text_parts),
                tool_calls=tuple(calls),
                finish_reason=stop_reason if isinstance(stop_reason, str) else None,
                usage=usage,
            )
        except (KeyError, TypeError) as exc:
            raise ProviderError("Anthropic returned an invalid Messages response shape.") from exc

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for item in tools:
            try:
                function = item["function"]
                name = function["name"]
                description = function.get("description", "")
                parameters = function.get("parameters", {"type": "object", "properties": {}})
                if not isinstance(name, str) or not name or not isinstance(parameters, dict):
                    raise TypeError("invalid function tool")
                converted.append({
                    "name": name,
                    "description": description if isinstance(description, str) else "",
                    "input_schema": parameters,
                })
            except (KeyError, TypeError) as exc:
                raise ProviderError("NextOrca supplied an invalid tool definition.") from exc
        return converted

    @classmethod
    def _convert_messages(
        cls, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        conversation: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []

        def flush_tool_results() -> None:
            if pending_tool_results:
                conversation.append({"role": "user", "content": list(pending_tool_results)})
                pending_tool_results.clear()

        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "system":
                if content:
                    if not isinstance(content, str):
                        raise ProviderError("Anthropic system messages must contain text.")
                    system_parts.append(content)
                continue
            if role == "tool":
                tool_call_id = message.get("tool_call_id")
                if not isinstance(tool_call_id, str) or not tool_call_id:
                    raise ProviderError("Tool result is missing its tool_call_id.")
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": content if isinstance(content, str) else json.dumps(content),
                })
                continue

            flush_tool_results()
            if role not in {"user", "assistant"}:
                raise ProviderError(f"Unsupported message role for Anthropic: {role!r}.")
            if not isinstance(content, (str, type(None))):
                raise ProviderError("Anthropic message content must be text or null.")
            blocks: list[dict[str, Any]] = []
            if content:
                blocks.append({"type": "text", "text": content})
            if role == "assistant":
                for item in message.get("tool_calls") or []:
                    try:
                        function = item["function"]
                        arguments = function["arguments"]
                        if isinstance(arguments, str):
                            arguments = json.loads(arguments)
                        if not isinstance(arguments, dict):
                            raise TypeError("tool arguments must be an object")
                        blocks.append({
                            "type": "tool_use",
                            "id": item["id"],
                            "name": function["name"],
                            "input": arguments,
                        })
                    except (KeyError, TypeError, json.JSONDecodeError) as exc:
                        raise ProviderError("Assistant history contains an invalid tool call.") from exc
            if not blocks:
                blocks.append({"type": "text", "text": ""})
            conversation.append({"role": role, "content": blocks if role == "assistant" else content or ""})
        flush_tool_results()
        return "\n\n".join(system_parts), conversation
