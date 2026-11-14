from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nextorca.cli_provider import (
    STRUCTURED_TURN_SCHEMA,
    build_cli_prompt,
    parse_structured_turn,
    run_cli_process,
)
from nextorca.provider import ProviderError
from nextorca.types import AssistantTurn

CLAUDE_SYSTEM_PROMPT = (
    "You are a text-only model adapter for NextOrca. Do not use tools or access the filesystem. "
    "Follow the system instructions included in the request data. Return a structured response "
    "containing content and tool_calls; NextOrca will execute any proposed tool calls."
)


class ClaudeCodeCLIProvider:
    """Use the user's authenticated Claude Code CLI as a structured chat backend."""

    def __init__(
        self,
        command: str | Sequence[str] = "claude",
        *,
        timeout_seconds: float = 180.0,
    ) -> None:
        normalized_command = (command,) if isinstance(command, str) else tuple(command)
        if not normalized_command or not normalized_command[0].strip():
            raise ValueError("A Claude Code CLI command is required.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        self.command = normalized_command
        self.timeout_seconds = timeout_seconds

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        if not model or not model.strip():
            raise ProviderError("A Claude model identifier is required.")
        prompt = build_cli_prompt(messages, tools)
        with tempfile.TemporaryDirectory(prefix="nextorca-claude-") as temporary:
            command = [
                *self.command,
                "--print",
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(STRUCTURED_TURN_SCHEMA, separators=(",", ":")),
                "--model",
                model,
                "--max-turns",
                "1",
                "--no-session-persistence",
                "--restricted",
                "--tools",
                "",
                "--strict-mcp-config",
                "--setting-sources",
                "",
                "--permission-mode",
                "plan",
                "--system-prompt",
                CLAUDE_SYSTEM_PROMPT,
            ]
            stdout, _stderr = run_cli_process(
                command,
                prompt,
                cwd=Path(temporary),
                timeout_seconds=self.timeout_seconds,
                extra_env={"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"},
            )
        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ProviderError("Claude Code CLI returned invalid JSON.") from exc
        if not isinstance(response, dict):
            raise ProviderError("Claude Code CLI returned an invalid response envelope.")
        structured = response.get("structured_output")
        if structured is None:
            raise ProviderError("Claude Code CLI did not return schema-validated structured output.")
        usage = response.get("usage")
        return parse_structured_turn(structured, tools, usage=usage if isinstance(usage, dict) else None)
