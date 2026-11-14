from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from nextorca.provider import ProviderError, ProviderUnavailableError
from nextorca.types import AssistantTurn, ToolCall

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MAX_OUTPUT_TOKENS = 8192
_GEMINI_SCHEMA_FIELDS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "items",
    "properties",
    "required",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "pattern",
    "anyOf",
}


class GeminiProvider:
    """Native adapter for Google's Gemini generateContent API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        client: httpx.Client | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive.")
        normalized_base_url = (base_url or DEFAULT_GEMINI_BASE_URL).rstrip("/")
        if not normalized_base_url.endswith(("/v1beta", "/v1")):
            normalized_base_url += "/v1beta"
        self.base_url = normalized_base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
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
        if not self.api_key:
            raise ProviderError("A Gemini API key is required.")
        if not model or not model.strip():
            raise ProviderError("A Gemini model identifier is required.")
        model_name = model.removeprefix("models/")
        endpoint = f"{self.base_url}/models/{quote(model_name, safe='-_.')}:generateContent"
        system, contents = self._convert_messages(messages)
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": self.max_output_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": self._convert_tools(tools)}]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

        try:
            response = self._client.post(
                endpoint,
                json=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Gemini request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            error_type = ProviderUnavailableError if status in {408, 429} or status >= 500 else ProviderError
            raise error_type(f"Gemini returned HTTP {status}.") from exc
        except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
            raise ProviderError("Gemini endpoint URL is invalid.") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("Gemini connection failed.") from exc
        except ValueError as exc:
            raise ProviderError("Gemini returned invalid JSON.") from exc

        try:
            candidates = payload["candidates"]
            if not isinstance(candidates, list) or not candidates:
                raise TypeError("candidates must be a non-empty list")
            candidate = candidates[0]
            content = candidate["content"]
            parts = content["parts"]
            if not isinstance(parts, list):
                raise TypeError("candidate parts must be a list")
            text_parts: list[str] = []
            calls: list[ToolCall] = []
            allowed_names = {item["name"] for item in self._convert_tools(tools)}
            for part in parts:
                if not isinstance(part, dict):
                    raise TypeError("candidate part must be an object")
                text = part.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
                function_call = part.get("functionCall")
                if function_call is not None:
                    if not isinstance(function_call, dict):
                        raise TypeError("functionCall must be an object")
                    name = function_call.get("name")
                    arguments = function_call.get("args", {})
                    if not isinstance(name, str) or name not in allowed_names:
                        raise ProviderError("Gemini requested a function that NextOrca did not provide.")
                    if not isinstance(arguments, dict):
                        raise TypeError("functionCall args must be an object")
                    calls.append(ToolCall(id=f"call_{uuid4().hex}", name=name, arguments=arguments))
            raw_usage = payload.get("usageMetadata") or {}
            usage: dict[str, int] = {}
            if isinstance(raw_usage, dict):
                for source, target in (("promptTokenCount", "input_tokens"), ("candidatesTokenCount", "output_tokens")):
                    value = raw_usage.get(source)
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        usage[target] = value
            finish_reason = candidate.get("finishReason")
            return AssistantTurn(
                content="\n".join(text_parts),
                tool_calls=tuple(calls),
                finish_reason=finish_reason if isinstance(finish_reason, str) else None,
                usage=usage,
            )
        except ProviderError:
            raise
        except (KeyError, TypeError) as exc:
            raise ProviderError("Gemini returned an invalid generateContent response shape.") from exc

    @classmethod
    def _convert_tools(cls, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        declarations: list[dict[str, Any]] = []
        for item in tools:
            try:
                function = item["function"]
                name = function["name"]
                parameters = function.get("parameters", {"type": "object", "properties": {}})
                if not isinstance(name, str) or not name or not isinstance(parameters, dict):
                    raise TypeError("invalid function declaration")
                description = function.get("description", "")
                declarations.append({
                    "name": name,
                    "description": description if isinstance(description, str) else "",
                    "parameters": cls._convert_schema(parameters),
                })
            except (KeyError, TypeError) as exc:
                raise ProviderError("NextOrca supplied an invalid Gemini function declaration.") from exc
        return declarations

    @classmethod
    def _convert_schema(cls, schema: dict[str, Any]) -> dict[str, Any]:
        converted: dict[str, Any] = {}
        for key, value in schema.items():
            if key not in _GEMINI_SCHEMA_FIELDS:
                continue
            if key == "type" and isinstance(value, str):
                converted[key] = value.upper()
            elif key == "properties" and isinstance(value, dict):
                converted[key] = {
                    name: cls._convert_schema(child)
                    for name, child in value.items()
                    if isinstance(name, str) and isinstance(child, dict)
                }
            elif key == "items" and isinstance(value, dict):
                converted[key] = cls._convert_schema(value)
            elif key == "anyOf" and isinstance(value, list):
                converted[key] = [cls._convert_schema(child) for child in value if isinstance(child, dict)]
            else:
                converted[key] = value
        if "type" not in converted:
            converted["type"] = "OBJECT"
        return converted

    @classmethod
    def _convert_messages(
        cls, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []
        call_names: dict[str, str] = {}
        for message in messages:
            if message.get("role") == "assistant":
                for call in message.get("tool_calls") or []:
                    try:
                        call_names[call["id"]] = call["function"]["name"]
                    except (KeyError, TypeError):
                        raise ProviderError("Assistant history contains an invalid function call.") from None

        def flush_tool_results() -> None:
            if pending_tool_results:
                contents.append({"role": "user", "parts": list(pending_tool_results)})
                pending_tool_results.clear()

        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "system":
                if content:
                    if not isinstance(content, str):
                        raise ProviderError("Gemini system messages must contain text.")
                    system_parts.append(content)
                continue
            if role == "tool":
                call_id = message.get("tool_call_id")
                name = call_names.get(call_id) if isinstance(call_id, str) else None
                if not name:
                    raise ProviderError("Gemini tool result does not match a previous function call.")
                response_content = content if isinstance(content, str) else json.dumps(content)
                pending_tool_results.append({
                    "functionResponse": {"name": name, "response": {"content": response_content}}
                })
                continue

            flush_tool_results()
            if role not in {"user", "assistant"}:
                raise ProviderError(f"Unsupported message role for Gemini: {role!r}.")
            if not isinstance(content, (str, type(None))):
                raise ProviderError("Gemini message content must be text or null.")
            parts: list[dict[str, Any]] = []
            if content:
                parts.append({"text": content})
            if role == "assistant":
                for call in message.get("tool_calls") or []:
                    try:
                        function = call["function"]
                        arguments = function["arguments"]
                        if isinstance(arguments, str):
                            arguments = json.loads(arguments)
                        if not isinstance(arguments, dict):
                            raise TypeError("function arguments must be an object")
                        parts.append({"functionCall": {"name": function["name"], "args": arguments}})
                    except (KeyError, TypeError, json.JSONDecodeError) as exc:
                        raise ProviderError("Assistant history contains an invalid function call.") from exc
            if not parts:
                parts.append({"text": ""})
            contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        flush_tool_results()
        return "\n\n".join(system_parts), contents
