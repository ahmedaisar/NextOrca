from __future__ import annotations

import json
import re
import uuid
from typing import Any


class ToolCallParseError(ValueError):
    """Raised when a model emits a malformed or unusable tool-call envelope."""


_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def parse_tool_calls(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Extract strict JSON tool-call envelopes; never silently discard invalid calls."""
    tool_uses: list[dict[str, Any]] = []

    def replace(match: re.Match[str]) -> str:
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ToolCallParseError(
                f"Malformed JSON in tool_call block at character {exc.pos}"
            ) from exc
        if not isinstance(payload, dict):
            raise ToolCallParseError("tool_call payload must be a JSON object")
        name = payload.get("name")
        arguments = payload.get("arguments", payload.get("input", {}))
        if not isinstance(name, str) or not name.strip():
            raise ToolCallParseError("tool_call payload requires a non-empty string name")
        if not isinstance(arguments, dict):
            raise ToolCallParseError("tool_call arguments must be a JSON object")
        tool_uses.append({
            "type": "tool_use",
            "id": f"toolu_{uuid.uuid4().hex[:24]}",
            "name": name,
            "input": arguments,
        })
        return ""

    return _TOOL_CALL_PATTERN.sub(replace, text).strip(), tool_uses


def build_anthropic_content(text: str) -> tuple[list[dict[str, Any]], str]:
    remaining, tool_uses = parse_tool_calls(text)
    content: list[dict[str, Any]] = []
    if remaining:
        content.append({"type": "text", "text": remaining})
    content.extend(tool_uses)
    return content, "tool_use" if tool_uses else "end_turn"


def openai_to_anthropic_response(oai: dict[str, Any]) -> dict[str, Any]:
    try:
        message = oai["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Local provider response is missing choices[0].message") from exc
    text = message.get("content") or ""
    if not isinstance(text, str):
        raise ValueError("Local provider message content must be a string")
    usage = oai.get("usage") or {}
    content, stop_reason = build_anthropic_content(text)
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": oai.get("model", "local-model"),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }
