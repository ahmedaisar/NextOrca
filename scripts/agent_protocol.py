from __future__ import annotations

import json
import re
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any


class ToolCallParseError(ValueError):
    """Raised when a local model emits an invalid or disallowed tool call."""


_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_TOOL_MARKERS = ("<tool_call>", "</tool_call>")
_ALLOWED_TOOLS = {"Read", "Glob", "Grep"}

_TOOL_ARGUMENTS: dict[str, dict[str, Any]] = {
    "Read": {
        "required": {"file_path": str},
        "optional": {"offset": int, "limit": int},
    },
    "Glob": {
        "required": {"pattern": str},
        "optional": {"path": str},
    },
    "Grep": {
        "required": {"pattern": str},
        "optional": {
            "path": str,
            "glob": str,
            "output_mode": str,
            "-B": int,
            "-A": int,
            "-C": int,
            "context_before": int,
            "context_after": int,
            "head_limit": int,
            "multiline": bool,
            "case_sensitive": bool,
            "fixed_string": bool,
            "type": str,
        },
    },
}


def _workspace_root(root: Path | str) -> Path:
    try:
        resolved = Path(root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ToolCallParseError("Configured workspace root is unavailable.") from exc
    if not resolved.is_dir():
        raise ToolCallParseError("Configured workspace root must be a directory.")
    return resolved


def _has_parent_component(value: str) -> bool:
    return ".." in re.split(r"[\\/]+", value)


def _resolve_workspace_path(
    value: str,
    root: Path,
    *,
    field_name: str,
    allow_root: bool,
) -> str:
    if not value or "\\x00" in value:
        raise ToolCallParseError(f"{field_name} must be a non-empty, valid path.")
    if _has_parent_component(value):
        raise ToolCallParseError(f"{field_name} cannot traverse outside the workspace.")
    supplied = Path(value).expanduser()
    if PureWindowsPath(value).is_absolute() and not supplied.is_absolute():
        raise ToolCallParseError(f"{field_name} must be within the configured workspace.")
    candidate = supplied if supplied.is_absolute() else root / supplied
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ToolCallParseError(f"{field_name} could not be resolved safely.") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolCallParseError(f"{field_name} escapes the configured workspace.") from exc
    if not allow_root and resolved == root:
        raise ToolCallParseError(f"{field_name} must identify a file inside the workspace.")
    return str(resolved)


def _validate_glob_pattern(pattern: str, field_name: str) -> None:
    if not pattern or "\\x00" in pattern:
        raise ToolCallParseError(f"{field_name} must be a non-empty pattern.")
    if PureWindowsPath(pattern).is_absolute() or Path(pattern).is_absolute():
        raise ToolCallParseError(f"{field_name} must be relative to the configured workspace.")
    if _has_parent_component(pattern):
        raise ToolCallParseError(f"{field_name} cannot traverse outside the workspace.")


def _validate_tool_arguments(
    name: str,
    arguments: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    if name not in _ALLOWED_TOOLS:
        raise ToolCallParseError(f"Local model tool '{name}' is not permitted.")

    schema = _TOOL_ARGUMENTS[name]
    allowed = set(schema["required"]) | set(schema["optional"])
    unknown = set(arguments) - allowed
    if unknown:
        raise ToolCallParseError(
            f"Local model tool '{name}' contains unsupported arguments: "
            + ", ".join(sorted(str(item) for item in unknown))
        )

    validated = dict(arguments)
    for field, expected_type in schema["required"].items():
        value = arguments.get(field)
        if not isinstance(value, expected_type) or (
            expected_type is str and not value.strip()
        ):
            raise ToolCallParseError(
                f"Local model tool '{name}' requires a valid '{field}' argument."
            )

    for field, expected_type in schema["optional"].items():
        if field not in arguments:
            continue
        value = arguments[field]
        if expected_type is int:
            valid = isinstance(value, int) and not isinstance(value, bool)
        else:
            valid = isinstance(value, expected_type)
        if not valid:
            raise ToolCallParseError(
                f"Local model tool '{name}' has an invalid '{field}' argument."
            )

    if name == "Read":
        for field in ("offset", "limit"):
            if field in arguments and arguments[field] < 0:
                raise ToolCallParseError(f"Read '{field}' must be zero or greater.")
        validated["file_path"] = _resolve_workspace_path(
            arguments["file_path"],
            workspace_root,
            field_name="Read.file_path",
            allow_root=False,
        )
    elif name == "Glob":
        _validate_glob_pattern(arguments["pattern"], "Glob.pattern")
        validated["path"] = _resolve_workspace_path(
            arguments.get("path", str(workspace_root)),
            workspace_root,
            field_name="Glob.path",
            allow_root=True,
        )
    else:
        if arguments.get("output_mode", "content") not in {"content", "files", "count"}:
            raise ToolCallParseError("Grep.output_mode must be content, files, or count.")
        for field in ("-B", "-A", "-C", "context_before", "context_after", "head_limit"):
            if field in arguments and arguments[field] < 0:
                raise ToolCallParseError(f"Grep '{field}' must be zero or greater.")
        if "glob" in arguments:
            _validate_glob_pattern(arguments["glob"], "Grep.glob")
        validated["path"] = _resolve_workspace_path(
            arguments.get("path", str(workspace_root)),
            workspace_root,
            field_name="Grep.path",
            allow_root=True,
        )

    return validated


def parse_tool_calls(
    text: str,
    workspace_root: Path | str,
) -> tuple[str, list[dict[str, Any]]]:
    """Parse local tool envelopes and enforce read-only, workspace-scoped tools."""
    root = _workspace_root(workspace_root)
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

        validated_arguments = _validate_tool_arguments(name, arguments, root)
        tool_uses.append(
            {
                "type": "tool_use",
                "id": f"toolu_{uuid.uuid4().hex[:24]}",
                "name": name,
                "input": validated_arguments,
            }
        )
        return ""

    remaining = _TOOL_CALL_PATTERN.sub(replace, text).strip()
    if any(marker in remaining for marker in _TOOL_MARKERS):
        raise ToolCallParseError("Unterminated or malformed tool_call marker.")
    return remaining, tool_uses


def build_anthropic_content(
    text: str,
    workspace_root: Path | str,
) -> tuple[list[dict[str, Any]], str]:
    remaining, tool_uses = parse_tool_calls(text, workspace_root)
    content: list[dict[str, Any]] = []
    if remaining:
        content.append({"type": "text", "text": remaining})
    content.extend(tool_uses)
    return content, "tool_use" if tool_uses else "end_turn"


def openai_to_anthropic_response(
    oai: dict[str, Any],
    workspace_root: Path | str,
) -> dict[str, Any]:
    try:
        message = oai["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Local provider response is missing choices[0].message") from exc
    text = message.get("content") or ""
    if not isinstance(text, str):
        raise TypeError("Local provider message content must be a string")
    usage = oai.get("usage") or {}
    content, stop_reason = build_anthropic_content(text, workspace_root)
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
