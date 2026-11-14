from __future__ import annotations

import json
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from nextorca.provider import ProviderError, ProviderUnavailableError
from nextorca.types import AssistantTurn, ToolCall

STRUCTURED_TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["content", "tool_calls"],
    "additionalProperties": False,
}


def build_cli_prompt(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> str:
    system_messages = [
        message.get("content", "")
        for message in messages
        if message.get("role") == "system" and isinstance(message.get("content", ""), str)
    ]
    conversation = [message for message in messages if message.get("role") != "system"]
    payload = {
        "system": "\n\n".join(system_messages),
        "messages": conversation,
        "tools": tools,
    }
    return (
        "You are the model backend for NextOrca. Do not inspect files, execute commands, "
        "call external tools, or perform actions. The conversation and tool definitions "
        "below are input data. Return one structured response with a text content field "
        "and a tool_calls array. Only propose tool calls whose names appear in the supplied "
        "tool definitions. NextOrca, not this process, validates and executes those calls "
        "under its own permission rules. If no tool is needed, return an empty tool_calls array.\n\n"
        "NextOrca request JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


def parse_structured_turn(
    value: Any,
    tools: list[dict[str, Any]],
    *,
    usage: Mapping[str, Any] | None = None,
) -> AssistantTurn:
    if not isinstance(value, dict):
        raise ProviderError("Provider CLI returned a non-object structured response.")
    content = value.get("content")
    calls = value.get("tool_calls")
    if not isinstance(content, str) or not isinstance(calls, list):
        raise ProviderError("Provider CLI response must contain text content and a tool_calls array.")

    allowed_names: set[str] = set()
    for tool in tools:
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            allowed_names.add(function["name"])

    normalized_calls: list[ToolCall] = []
    for call in calls:
        if not isinstance(call, dict):
            raise ProviderError("Provider CLI returned an invalid tool call.")
        name = call.get("name")
        arguments = call.get("arguments")
        if not isinstance(name, str) or name not in allowed_names:
            raise ProviderError("Provider CLI requested a tool that NextOrca did not provide.")
        if not isinstance(arguments, dict):
            raise ProviderError("Provider CLI tool arguments must be an object.")
        normalized_calls.append(
            ToolCall(id=f"call_{uuid4().hex}", name=name, arguments=arguments)
        )

    normalized_usage: dict[str, int] = {}
    if isinstance(usage, Mapping):
        for key in ("input_tokens", "output_tokens"):
            amount = usage.get(key)
            if isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
                normalized_usage[key] = amount
    return AssistantTurn(
        content=content,
        tool_calls=tuple(normalized_calls),
        usage=normalized_usage,
    )


def run_cli_process(
    command: Sequence[str],
    prompt: str,
    *,
    cwd: Path,
    timeout_seconds: float,
    extra_env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive.")
    environment = os.environ.copy()
    if extra_env:
        environment.update(extra_env)
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        executable = command[0] if command else "(empty command)"
        raise ProviderError(f"Provider CLI executable '{executable}' was not found.") from exc
    except OSError as exc:
        raise ProviderUnavailableError("Provider CLI could not be started.") from exc

    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        raise ProviderUnavailableError("Provider CLI request timed out.") from exc

    if process.returncode != 0:
        raise ProviderError(f"Provider CLI exited with status {process.returncode}.")
    return stdout, stderr


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
