from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from nextorca.tool_registry import PreparedToolOperation, ToolSpec
from nextorca.workspace import Workspace

MAX_COMMAND_CHARS = 10_000
MAX_TIMEOUT_SECONDS = 600
MAX_OUTPUT_CHARS = 30_000


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _run(command: str, workspace: Workspace, timeout_seconds: int) -> str:
    try:
        completed = subprocess.run(
            command,
            shell=True,
            executable=(
                "/bin/bash"
                if os.name != "nt" and Path("/bin/bash").is_file()
                else None
            ),
            cwd=workspace.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        result = f"Exit code: {completed.returncode}\n{output}"
    except subprocess.TimeoutExpired as exc:
        output = _decode(exc.stdout) + _decode(exc.stderr)
        result = f"Command timed out after {timeout_seconds} seconds.\n{output}"
    except OSError as exc:
        result = f"Command could not be started: {type(exc).__name__}: {exc}"
    if len(result) > MAX_OUTPUT_CHARS:
        result = result[:MAX_OUTPUT_CHARS] + "\n[command output truncated]"
    return result


def build_shell_tool(workspace: Workspace) -> ToolSpec:
    """Create the interactive shell tool. Every call is an approved, visible action."""

    def prepare(arguments: dict[str, Any]) -> PreparedToolOperation:
        command = arguments["command"]
        timeout_seconds = arguments.get("timeout_seconds", 120)
        if not command.strip():
            raise ValueError("Shell command must not be empty.")
        if timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(f"Shell timeout cannot exceed {MAX_TIMEOUT_SECONDS} seconds.")
        preview = (
            f"Working directory: {workspace.root}\n"
            f"Timeout: {timeout_seconds}s\n"
            f"Command:\n{command}"
        )
        return PreparedToolOperation(
            preview=preview,
            execute=lambda: _run(command, workspace, timeout_seconds),
        )

    return ToolSpec(
        name="Shell",
        description=(
            "Run a shell command in the current project directory. Use for tests, linters, "
            "builds and git. Commands may read or modify the working tree and can access the "
            "same host permissions as the user. Every invocation is shown to the user and "
            "requires explicit approval. Keep commands focused and set a reasonable timeout."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_COMMAND_CHARS,
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        handler=lambda _args: "Shell operations must be prepared and approved.",
        read_only=False,
        prepare_handler=prepare,
    )
