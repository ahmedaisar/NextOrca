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


DISABLED_CODEX_FEATURES = (
    "shell_tool",
    "unified_exec",
    "unified_exec_tty",
    "code_mode_host",
    "incremental_tools",
    "view_image",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "apps",
    "plugins",
    "workspace_dependencies",
    "worktrees",
    "sleep_tool",
    "code_mode_interrupt",
    "shell_snapshot",
    "browser_annotation_api",
    "in_app_browser",
    "in_app_local_automation",
    "multi_agent",
    "plugin_discovery_prefetch",
    "plugin_sharing",
    "remote_plugin",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_call_mcp_elicitation",
    "tool_search_always_defer_mcp_tools",
    "tool_suggest",
    "write_stdin_approval",
)


class CodexCLIProvider:
    """Use the user's authenticated Codex CLI without exposing the project workspace."""

    def __init__(
        self,
        command: str | Sequence[str] = "codex",
        *,
        timeout_seconds: float = 180.0,
    ) -> None:
        normalized_command = (command,) if isinstance(command, str) else tuple(command)
        if not normalized_command or not normalized_command[0].strip():
            raise ValueError("A Codex CLI command is required.")
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
            raise ProviderError("A Codex model identifier is required.")
        prompt = build_cli_prompt(messages, tools)
        with tempfile.TemporaryDirectory(prefix="nextorca-codex-") as temporary:
            directory = Path(temporary)
            schema_path = directory / "response-schema.json"
            output_path = directory / "last-message.json"
            schema_path.write_text(json.dumps(STRUCTURED_TURN_SCHEMA), encoding="utf-8")
            command = [
                *self.command,
                "exec",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--model",
                model,
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--cd",
                temporary,
            ]
            for feature in DISABLED_CODEX_FEATURES:
                command.extend(["--disable", feature])
            command.append("-")
            run_cli_process(
                command,
                prompt,
                cwd=directory,
                timeout_seconds=self.timeout_seconds,
            )
            if not output_path.is_file():
                raise ProviderError("Codex CLI did not write its schema-validated final response.")
            try:
                structured = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProviderError("Codex CLI returned invalid structured JSON.") from exc
        return parse_structured_turn(structured, tools)
