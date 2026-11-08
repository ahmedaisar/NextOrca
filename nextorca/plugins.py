from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from nextorca.tool_registry import PreparedToolOperation, ToolSpec
from nextorca.workspace import Workspace

PLUGIN_LOCATIONS = (Path(".nextorca") / "plugins",)
PLUGIN_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
PLACEHOLDER = re.compile(r"^\{([a-zA-Z_][a-zA-Z0-9_]*)\}$")
MAX_MANIFEST_BYTES = 64_000
MAX_PLUGIN_OUTPUT_CHARS = 24_000
MAX_PLUGIN_TIMEOUT = 600


@dataclass(frozen=True)
class Plugin:
    name: str
    description: str
    root: Path
    skill_roots: tuple[Path, ...]
    tools: tuple[dict[str, Any], ...]


def _safe_relative_path(value: str) -> bool:
    path = Path(value)
    return (
        bool(value)
        and "\x00" not in value
        and not path.is_absolute()
        and not PureWindowsPath(value).is_absolute()
        and ".." not in value.replace("\\", "/").split("/")
        and all(part not in {"", "."} for part in value.replace("\\", "/").split("/"))
    )


def _validate_tool(tool: Any) -> dict[str, Any]:
    if not isinstance(tool, dict) or set(tool) - {
        "name", "description", "command", "parameters", "timeout_seconds"
    }:
        raise ValueError("Plugin tool has an invalid shape or unsupported fields.")
    name = tool.get("name")
    description = tool.get("description")
    command = tool.get("command")
    parameters = tool.get("parameters")
    timeout = tool.get("timeout_seconds", 120)
    if not isinstance(name, str) or not TOOL_NAME.fullmatch(name):
        raise ValueError("Plugin tool name must be a lowercase identifier.")
    if not isinstance(description, str) or not description.strip() or len(description) > 2_000:
        raise ValueError(f"Plugin tool {name!r} requires a description of at most 2000 characters.")
    if (
        not isinstance(command, list)
        or not command
        or len(command) > 32
        or not all(isinstance(item, str) and item and "\x00" not in item for item in command)
    ):
        raise ValueError(f"Plugin tool {name!r} command must be a non-empty argv array.")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= MAX_PLUGIN_TIMEOUT:
        raise ValueError(f"Plugin tool {name!r} timeout must be between 1 and {MAX_PLUGIN_TIMEOUT} seconds.")
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        raise ValueError(f"Plugin tool {name!r} parameters must be an object schema.")
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ValueError(f"Plugin tool {name!r} has invalid properties or required fields.")
    if parameters.get("additionalProperties", False) is not False:
        raise ValueError(f"Plugin tool {name!r} must reject additional properties.")
    for key, definition in properties.items():
        if not isinstance(key, str) or not isinstance(definition, dict):
            raise ValueError(f"Plugin tool {name!r} has an invalid property definition.")
        if definition.get("type") not in {"string", "integer", "number", "boolean"}:
            raise ValueError("Plugin command placeholders support only scalar argument types.")
    if any(not isinstance(key, str) or key not in properties for key in required):
        raise ValueError(f"Plugin tool {name!r} has an unknown required field.")
    placeholders = {
        match.group(1)
        for token in command
        if (match := PLACEHOLDER.fullmatch(token)) is not None
    }
    if any("{" in token or "}" in token for token in command if PLACEHOLDER.fullmatch(token) is None):
        raise ValueError(f"Plugin tool {name!r} placeholders must occupy a complete argv token.")
    if not placeholders.issubset(properties):
        raise ValueError(f"Plugin tool {name!r} uses undeclared command placeholders.")
    return {
        "name": name,
        "description": description,
        "command": command,
        "parameters": parameters,
        "timeout_seconds": timeout,
    }


def _load_plugin(directory: Path, expected_root: Path) -> Plugin:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Plugin directory must be a regular directory.")
    root = directory.resolve(strict=True)
    root.relative_to(expected_root)
    manifest_path = directory / "plugin.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Plugin must contain a regular plugin.json file.")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Plugin manifest exceeds the size limit.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) - {
        "schema_version", "name", "description", "skills", "tools"
    }:
        raise ValueError("Plugin manifest has an invalid shape or unsupported fields.")
    if manifest.get("schema_version") != 1:
        raise ValueError("Only plugin manifest schema_version 1 is supported.")
    name = manifest.get("name")
    description = manifest.get("description")
    if not isinstance(name, str) or not PLUGIN_NAME.fullmatch(name) or directory.name != name:
        raise ValueError("Plugin name must be a lowercase ID matching its directory.")
    if not isinstance(description, str) or not description.strip() or len(description) > 2_000:
        raise ValueError("Plugin description is required and limited to 2000 characters.")

    skill_values = manifest.get("skills", [])
    tool_values = manifest.get("tools", [])
    if not isinstance(skill_values, list) or not isinstance(tool_values, list):
        raise ValueError("Plugin skills and tools must be arrays.")
    skill_roots: list[Path] = []
    for value in skill_values:
        if not isinstance(value, str) or not _safe_relative_path(value):
            raise ValueError("Plugin skill paths must be safe relative directories.")
        candidate = directory / value
        if candidate.is_symlink() or not candidate.is_dir():
            raise ValueError(f"Plugin skill directory {value!r} is unavailable or symlinked.")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        skill_roots.append(resolved)
    tools = tuple(_validate_tool(value) for value in tool_values)
    if len({tool["name"] for tool in tools}) != len(tools):
        raise ValueError("Plugin tool names must be unique within a plugin.")
    return Plugin(name, description, root, tuple(skill_roots), tools)


def discover_plugins(
    workspace_root: Path | str,
    *,
    home: Path | str | None = None,
) -> tuple[list[Plugin], list[str]]:
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    user_home = Path(home).expanduser() if home is not None else Path.home()
    roots = [workspace / relative for relative in PLUGIN_LOCATIONS]
    roots.append(user_home / ".nextorca" / "plugins")
    found: dict[str, Plugin] = {}
    errors: list[str] = []
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            continue
        expected_parent = workspace if root.is_relative_to(workspace) else user_home.resolve()
        try:
            canonical_root = root.resolve(strict=True)
            canonical_root.relative_to(expected_parent)
        except (OSError, RuntimeError, ValueError):
            errors.append(f"Skipped plugin directory outside its expected root: {root}")
            continue
        for directory in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            try:
                plugin = _load_plugin(directory, canonical_root)
            except (OSError, UnicodeError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                if directory.is_dir() and not directory.is_symlink():
                    errors.append(f"Skipped plugin {directory}: {exc}")
                continue
            if plugin.name in found:
                errors.append(
                    f"Plugin {plugin.name!r} from {directory} ignored; "
                    f"the higher-priority copy at {found[plugin.name].root} wins."
                )
                continue
            found[plugin.name] = plugin
    return list(found.values()), errors


def _stringify_argument(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_plugin_tools(plugin: Plugin, workspace: Workspace) -> list[ToolSpec]:
    result: list[ToolSpec] = []
    for definition in plugin.tools:
        command_template = definition["command"]
        parameters = definition["parameters"]
        timeout_seconds = definition["timeout_seconds"]
        tool_name = f"plugin_{plugin.name.replace('-', '_')}_{definition['name']}"

        def prepare(
            arguments: dict[str, Any],
            *,
            template: list[str] = command_template,
            timeout: int = timeout_seconds,
            plugin_name: str = plugin.name,
            local_name: str = definition["name"],
        ) -> PreparedToolOperation:
            argv = [
                _stringify_argument(arguments[match.group(1)])
                if (match := PLACEHOLDER.fullmatch(token)) is not None
                and match.group(1) in arguments
                else token
                for token in template
                if not (
                    (match := PLACEHOLDER.fullmatch(token)) is not None
                    and match.group(1) not in arguments
                )
            ]
            preview = (
                f"Plugin: {plugin_name}\nTool: {local_name}\n"
                f"Working directory: {workspace.root}\n"
                f"Command: {shlex.join(argv)}\nTimeout: {timeout}s"
            )

            def execute() -> str:
                try:
                    completed = subprocess.run(
                        argv,
                        cwd=workspace.root,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=timeout,
                        check=False,
                    )
                    output = (completed.stdout or "") + (completed.stderr or "")
                    text = f"Exit code: {completed.returncode}\n{output}"
                except subprocess.TimeoutExpired as exc:
                    stdout = exc.stdout or ""
                    stderr = exc.stderr or ""
                    if isinstance(stdout, bytes):
                        stdout = stdout.decode("utf-8", errors="replace")
                    if isinstance(stderr, bytes):
                        stderr = stderr.decode("utf-8", errors="replace")
                    text = f"Plugin command timed out after {timeout}s.\n{stdout}{stderr}"
                except OSError as exc:
                    text = f"Plugin command could not start: {type(exc).__name__}: {exc}"
                if len(text) > MAX_PLUGIN_OUTPUT_CHARS:
                    text = text[:MAX_PLUGIN_OUTPUT_CHARS] + "\n[plugin output truncated]"
                return text

            return PreparedToolOperation(preview=preview, execute=execute)

        result.append(
            ToolSpec(
                name=tool_name,
                description=f"[Plugin {plugin.name}] {definition['description']}",
                parameters=parameters,
                handler=lambda _args: "Plugin commands must be prepared and approved.",
                read_only=False,
                prepare_handler=prepare,
            )
        )
    return result


def format_plugin_catalog(plugins: list[Plugin]) -> str:
    if not plugins:
        return ""
    lines = ["The following local plugins are loaded. Their tools require explicit approval."]
    lines.extend(f"- {plugin.name}: {plugin.description}" for plugin in plugins)
    return "\n\nPlugins:\n" + "\n".join(lines)
