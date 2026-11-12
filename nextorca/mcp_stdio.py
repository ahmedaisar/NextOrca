from __future__ import annotations

import json
import math

# ruff: isort: off
import os
import queue
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from nextorca.sandbox import LinuxBubblewrapSandbox, SandboxError
from nextorca.tool_registry import (
    PreparedToolOperation,
    ToolExecutionError,
    ToolRegistry,
    ToolSpec,
)
# ruff: isort: on


MODERN_PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSION = "2025-11-25"
LEGACY_PROTOCOL_VERSIONS = {"2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07"}
MAX_MCP_SERVERS = 8
MAX_CONFIG_BYTES = 64_000
MAX_MCP_TOOLS_PER_SERVER = 128
MAX_MESSAGE_CHARS = 1_000_000
MAX_TOOL_SCHEMA_CHARS = 64_000
MAX_TOOL_NAME_LENGTH = 128
MAX_OUTPUT_CHARS = 48_000

_SAFE_INHERITED_ENV = {
    "PATH",
    "HOME",
    "USERPROFILE",
    "TMP",
    "TEMP",
    "TMPDIR",
    "SYSTEMROOT",
    "WINDIR",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PATHEXT",
    "COMSPEC",
}


_SCHEMA_KEYS = {
    "type", "title", "description", "properties", "required",
    "additionalProperties", "items", "enum", "minLength", "maxLength",
    "minimum", "maximum", "minItems", "maxItems", "minProperties",
    "maxProperties",
}


def _validate_schema_definition(
    schema: dict[str, Any], *, tool_name: str, depth: int
) -> None:
    if depth > 8:
        raise MCPServerError(f"MCP tool '{tool_name}' input schema exceeds nesting limit.")
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        raise MCPServerError(
            f"MCP tool '{tool_name}' uses unsupported schema keywords: "
            + ", ".join(sorted(str(key) for key in unknown))
        )
    expected = schema.get("type", "object")
    if expected not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        raise MCPServerError(f"MCP tool '{tool_name}' uses an unsupported JSON Schema type.")
    for key in ("minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties"):
        if key in schema and (
            isinstance(schema[key], bool)
            or not isinstance(schema[key], int)
            or schema[key] < 0
            or schema[key] > 1_000_000
        ):
            raise MCPServerError(f"MCP tool '{tool_name}' has an invalid {key} constraint.")
    for key in ("minimum", "maximum"):
        if key in schema and (
            isinstance(schema[key], bool) or not isinstance(schema[key], (int, float))
        ):
            raise MCPServerError(f"MCP tool '{tool_name}' has an invalid {key} constraint.")
    if "enum" in schema and (
        not isinstance(schema["enum"], list) or len(schema["enum"]) > 256
    ):
        raise MCPServerError(f"MCP tool '{tool_name}' has an invalid enum constraint.")
    if expected == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", False)
        if not isinstance(properties, dict) or len(properties) > 256:
            raise MCPServerError(f"MCP tool '{tool_name}' has invalid object properties.")
        if not isinstance(required, list) or not all(
            isinstance(item, str) and item in properties for item in required
        ):
            raise MCPServerError(f"MCP tool '{tool_name}' has invalid required properties.")
        if not isinstance(additional, bool):
            raise MCPServerError(
                f"MCP tool '{tool_name}' cannot use schema-valued additionalProperties."
            )
        for name, definition in properties.items():
            if not isinstance(name, str) or not isinstance(definition, dict):
                raise MCPServerError(f"MCP tool '{tool_name}' has an invalid property schema.")
            _validate_schema_definition(definition, tool_name=tool_name, depth=depth + 1)
    if expected == "array":
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            raise MCPServerError(f"MCP tool '{tool_name}' array schema requires an items schema.")
        _validate_schema_definition(item_schema, tool_name=tool_name, depth=depth + 1)


def _validate_remote_value(
    schema: dict[str, Any], value: Any, *, tool_name: str, path: str, depth: int
) -> None:
    if depth > 8:
        raise ToolExecutionError(f"MCP argument {path} exceeds the nesting limit.")
    expected = schema.get("type", "object")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)
    if not valid:
        raise ToolExecutionError(f"MCP argument {path} must be {expected}.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ToolExecutionError(f"MCP argument {path} must be a finite number.")
    if isinstance(value, str) and (
        len(value) < schema.get("minLength", 0)
        or len(value) > schema.get("maxLength", 100_000)
    ):
        raise ToolExecutionError(f"MCP argument {path} violates its length limits.")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolExecutionError(f"MCP argument {path} is below its minimum.")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolExecutionError(f"MCP argument {path} exceeds its maximum.")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolExecutionError(f"MCP argument {path} is not an allowed value.")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", False)
        missing = [key for key in required if key not in value]
        if missing:
            raise ToolExecutionError(
                f"MCP argument {path} is missing required fields: " + ", ".join(missing)
            )
        unknown = set(value) - set(properties)
        if unknown and not additional:
            raise ToolExecutionError(
                f"MCP argument {path} has unsupported fields: "
                + ", ".join(sorted(str(key) for key in unknown))
            )
        if len(value) > schema.get("maxProperties", 1_000_000):
            raise ToolExecutionError(f"MCP argument {path} has too many fields.")
        for key, child in value.items():
            if key in properties:
                _validate_remote_value(
                    properties[key], child, tool_name=tool_name,
                    path=f"{path}.{key}", depth=depth + 1
                )
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 1_000_000):
            raise ToolExecutionError(f"MCP argument {path} violates its item-count limits.")
        for index, item in enumerate(value):
            _validate_remote_value(
                schema["items"], item, tool_name=tool_name,
                path=f"{path}[{index}]", depth=depth + 1
            )


def _validate_remote_arguments(
    schema: dict[str, Any], arguments: dict[str, Any], *, tool_name: str
) -> None:
    _validate_remote_value(schema, arguments, tool_name=tool_name, path="arguments", depth=0)


class MCPServerError(RuntimeError):
    """An MCP server or its stdio protocol failed."""


class MCPMethodNotFound(MCPServerError):
    """The server does not implement a requested JSON-RPC method."""


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: tuple[str, ...]
    env_passthrough: tuple[str, ...] = ()
    cwd: str | None = None
    timeout_seconds: float = 15.0
    network_access: bool = False
    writable_paths: tuple[str, ...] = ()


def load_mcp_config(path: Path | str) -> list[MCPServerConfig]:
    """Load a bounded MCP stdio manifest without executing any command."""
    config_path = Path(path).expanduser()
    try:
        if config_path.stat().st_size > MAX_CONFIG_BYTES:
            raise MCPServerError("MCP configuration exceeds the 64 KB size limit.")
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except MCPServerError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MCPServerError("MCP configuration could not be read as valid JSON.") from exc

    if (
        not isinstance(payload, dict)
        or set(payload) != {"servers"}
        or not isinstance(payload.get("servers"), list)
    ):
        raise MCPServerError("MCP configuration must contain only a 'servers' array.")
    rows = payload["servers"]
    if len(rows) > MAX_MCP_SERVERS:
        raise MCPServerError(f"At most {MAX_MCP_SERVERS} MCP servers may be configured.")

    configs: list[MCPServerConfig] = []
    names: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MCPServerError(f"MCP server entry {index} must be an object.")
        allowed_fields = {
            "name", "command", "env_passthrough", "cwd",
            "timeout_seconds", "network_access", "writable_paths",
        }
        unknown_fields = set(row) - allowed_fields
        if unknown_fields:
            raise MCPServerError(
                f"MCP server entry {index} has unsupported fields: "
                + ", ".join(sorted(str(field) for field in unknown_fields))
            )
        name = row.get("name")
        command = row.get("command")
        env_passthrough = row.get("env_passthrough", [])
        cwd = row.get("cwd")
        timeout = row.get("timeout_seconds", 15.0)
        network_access = row.get("network_access", False)
        writable_paths = row.get("writable_paths", [])

        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
            raise MCPServerError(f"MCP server entry {index} has an invalid name.")
        if name.lower() in names:
            raise MCPServerError(f"MCP server name '{name}' is duplicated.")
        names.add(name.lower())
        if (
            not isinstance(command, list)
            or not command
            or len(command) > 64
            or not all(isinstance(part, str) and part and "\x00" not in part for part in command)
        ):
            raise MCPServerError(
                f"MCP server '{name}' command must be a non-empty array of strings."
            )
        if any(len(part) > 8_192 for part in command):
            raise MCPServerError(f"MCP server '{name}' command argument is too long.")
        if (
            not isinstance(env_passthrough, list)
            or len(env_passthrough) > 64
            or not all(
                isinstance(key, str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
                for key in env_passthrough
            )
        ):
            raise MCPServerError(f"MCP server '{name}' env_passthrough must be an array of variable names.")
        if cwd is not None and (not isinstance(cwd, str) or not cwd or "\x00" in cwd):
            raise MCPServerError(f"MCP server '{name}' cwd must be a non-empty path string.")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0.5 <= float(timeout) <= 120.0
        ):
            raise MCPServerError(f"MCP server '{name}' timeout_seconds must be between 0.5 and 120.")

        if not isinstance(network_access, bool):
            raise MCPServerError(f"MCP server '{name}' network_access must be a boolean.")
        if (
            not isinstance(writable_paths, list)
            or len(writable_paths) > 32
            or not all(
                isinstance(value, str) and 0 < len(value) <= 256
                for value in writable_paths
            )
        ):
            raise MCPServerError(
                f"MCP server '{name}' writable_paths must be an array of at most 32 paths."
            )

        configs.append(
            MCPServerConfig(
                name=name,
                command=tuple(command),
                env_passthrough=tuple(env_passthrough),
                cwd=cwd,
                timeout_seconds=float(timeout),
                network_access=network_access,
                writable_paths=tuple(writable_paths),
            )
        )
    return configs


class MCPStdioClient:
    """MCP stdio client with 2026 stateless discovery and legacy handshake fallback."""

    def __init__(
        self,
        config: MCPServerConfig,
        *,
        workspace_root: Path | str,
        request_timeout_seconds: float | None = None,
    ) -> None:
        self.config = config
        self.workspace_root = Path(workspace_root).expanduser().resolve(strict=True)
        if not self.workspace_root.is_dir():
            raise MCPServerError("MCP working directory must be an existing directory.")
        self.request_timeout_seconds = request_timeout_seconds or config.timeout_seconds
        if not 0.5 <= self.request_timeout_seconds <= 120:
            raise ValueError("MCP request timeout must be between 0.5 and 120 seconds.")
        try:
            self.sandbox = LinuxBubblewrapSandbox(
                self.workspace_root,
                allow_network=config.network_access,
                writable_paths=config.writable_paths,
            )
        except SandboxError as exc:
            raise MCPServerError(str(exc)) from exc

        self.process: subprocess.Popen[str] | None = None
        self.protocol_era: str | None = None
        self.protocol_version: str | None = None
        self.server_info: dict[str, Any] = {}
        self.server_instructions = ""
        self._responses: queue.Queue[str | BaseException | None] = queue.Queue(maxsize=64)
        self._reader: threading.Thread | None = None
        self._request_id = 0
        self._request_lock = threading.Lock()
        self._closed = False

    def _process_environment(self) -> dict[str, str]:
        # bubblewrap owns PATH, HOME, temp paths, locale and workspace identity.
        # Only explicitly named application variables cross into the sandbox.
        return {
            key: os.environ[key]
            for key in self.config.env_passthrough
            if key in os.environ
        }

    def _start_process(self) -> None:
        if self._closed:
            raise MCPServerError("MCP client is closed.")
        command = list(self.config.command)
        cwd = self.workspace_root
        if self.config.cwd is not None:
            requested_cwd = Path(self.config.cwd).expanduser()
            if not requested_cwd.is_absolute():
                requested_cwd = self.workspace_root / requested_cwd
            try:
                cwd = requested_cwd.resolve(strict=True)
                cwd.relative_to(self.workspace_root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise MCPServerError(
                    f"MCP server '{self.config.name}' working directory escapes the workspace."
                ) from exc
            if not cwd.is_dir():
                raise MCPServerError(f"MCP server '{self.config.name}' working directory is not a directory.")

        try:
            sandbox_command, outer_environment = self.sandbox.wrap(
                command,
                working_directory=cwd,
                environment=self._process_environment(),
            )
            self.process = subprocess.Popen(
                sandbox_command,
                cwd=cwd,
                env=outer_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="strict",
                bufsize=1,
                shell=False,
                start_new_session=True,
                pass_fds=self.sandbox.pass_fds,
            )
        except (OSError, ValueError, SandboxError) as exc:
            raise MCPServerError(
                f"MCP server '{self.config.name}' could not be started."
            ) from exc

        self._responses = queue.Queue(maxsize=64)
        self._reader = threading.Thread(
            target=self._read_stdout,
            name=f"nextorca-mcp-{self.config.name}",
            daemon=True,
        )
        self._reader.start()

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            while True:
                line = process.stdout.readline(MAX_MESSAGE_CHARS + 1)
                if not line:
                    self._responses.put(None)
                    return
                if len(line) > MAX_MESSAGE_CHARS:
                    self._responses.put(
                        MCPServerError("MCP server message exceeded the 1 MB limit.")
                    )
                    return
                self._responses.put(line)
        except (OSError, UnicodeError, ValueError) as exc:
            self._responses.put(MCPServerError(f"MCP server stdout failed: {type(exc).__name__}"))

    def _write_message(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MCPServerError("MCP server process is not running.")
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > MAX_MESSAGE_CHARS:
            raise MCPServerError("MCP request exceeded the 1 MB message limit.")
        try:
            self.process.stdin.write(encoded + "\n")
            self.process.stdin.flush()
        except (OSError, BrokenPipeError, UnicodeError) as exc:
            raise MCPServerError("MCP request could not be written to server stdin.") from exc

    def _request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        with self._request_lock:
            if self.process is None or self.process.poll() is not None:
                raise MCPServerError(f"MCP server '{self.config.name}' is not running.")
            self._request_id += 1
            request_id = self._request_id
            request_params = dict(params or {})
            if self.protocol_era == "modern" or method == "server/discover":
                request_params["_meta"] = {
                    "io.modelcontextprotocol/protocolVersion": MODERN_PROTOCOL_VERSION,
                    "io.modelcontextprotocol/clientInfo": {
                        "name": "NextOrca",
                        "version": "0.8.0",
                    },
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": request_params,
            }
            self._write_message(request)

            timeout = timeout_seconds or self.request_timeout_seconds
            deadline = time.monotonic() + timeout
            ignored_messages = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._stop_process(force=True)
                    raise MCPServerError(
                        f"MCP server '{self.config.name}' timed out handling {method}; process terminated."
                    )
                try:
                    line = self._responses.get(timeout=remaining)
                except queue.Empty as exc:
                    self._stop_process(force=True)
                    raise MCPServerError(
                        f"MCP server '{self.config.name}' timed out handling {method}; process terminated."
                    ) from exc

                if line is None:
                    code = self.process.poll() if self.process is not None else None
                    raise MCPServerError(
                        f"MCP server '{self.config.name}' closed stdout (exit code {code})."
                    )
                if isinstance(line, BaseException):
                    raise MCPServerError(str(line))

                try:
                    response = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise MCPServerError("MCP server returned invalid JSON.") from exc
                if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
                    raise MCPServerError("MCP server returned an invalid JSON-RPC message.")

                if "method" in response and "id" not in response:
                    ignored_messages += 1
                    if ignored_messages > 128:
                        raise MCPServerError("MCP server sent too many notifications during a request.")
                    continue
                if type(response.get("id")) is not int or response["id"] != request_id:
                    ignored_messages += 1
                    if ignored_messages > 128:
                        raise MCPServerError("MCP server returned too many unrelated messages.")
                    continue
                if "error" in response:
                    error = response.get("error")
                    if isinstance(error, dict):
                        code = error.get("code")
                        message = str(error.get("message", "MCP request failed"))
                        data = error.get("data")
                        error_text = (
                            f"MCP {method} failed ({code}): {message}; "
                            f"data={json.dumps(data, ensure_ascii=False)[:2000]}"
                        )
                        if code == -32601:
                            raise MCPMethodNotFound(error_text)
                        raise MCPServerError(error_text)
                    raise MCPServerError(f"MCP {method} returned a malformed error.")
                result = response.get("result")
                if not isinstance(result, dict):
                    raise MCPServerError(f"MCP {method} returned a non-object result.")
                if self.protocol_era == "modern" and method != "server/discover":
                    result_type = result.get("resultType")
                    if result_type == "input_required":
                        raise MCPServerError(
                            f"MCP {method} requires interactive protocol input, which NextOrca "
                            "does not implement; the response was rejected."
                        )
                    if result_type != "complete":
                        raise MCPServerError(
                            f"MCP {method} returned an incomplete or missing modern resultType."
                        )
                return result

    def connect(self) -> None:
        try:
            self._connect()
        except Exception:
            self.close()
            raise

    def _connect(self) -> None:
        self._start_process()

        # Probe modern stateless discovery first. Fall back only when the request
        # itself is unsupported or the server is silent/exits before responding.
        try:
            discovery = self._request(
                "server/discover",
                timeout_seconds=min(3.0, self.request_timeout_seconds),
            )
        except MCPMethodNotFound:
            # Standard JSON-RPC method-not-found is the legacy compatibility probe.
            pass
        except MCPServerError:
            if self.process is None or self.process.poll() is not None:
                # Restart after a discovery timeout/exit before attempting the legacy handshake.
                self._stop_process(force=True)
                self._start_process()
            else:
                raise
        else:
            # Validate a received discovery response outside the fallback handler.
            # Malformed modern responses must fail with their actual validation error.
            if discovery.get("resultType") != "complete":
                raise MCPServerError("MCP server/discover did not complete protocol discovery.")
            supported = discovery.get("supportedVersions")
            capabilities = discovery.get("capabilities")
            cache_scope = discovery.get("cacheScope")
            ttl_ms = discovery.get("ttlMs")
            if (
                not isinstance(supported, list)
                or not supported
                or len(supported) > 32
                or not all(isinstance(version, str) and version for version in supported)
            ):
                raise MCPServerError("MCP server/discover omitted valid supportedVersions.")
            if not isinstance(capabilities, dict):
                raise MCPServerError("MCP server/discover omitted valid capabilities.")
            if cache_scope not in {"public", "private"}:
                raise MCPServerError("MCP server/discover returned an invalid cacheScope.")
            if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int) or ttl_ms < 0:
                raise MCPServerError("MCP server/discover returned an invalid ttlMs.")
            if MODERN_PROTOCOL_VERSION not in supported:
                raise MCPServerError(
                    f"MCP server '{self.config.name}' has no mutually supported modern protocol version."
                )
            self.protocol_era = "modern"
            self.protocol_version = MODERN_PROTOCOL_VERSION
            self.server_instructions = str(discovery.get("instructions", ""))[:4_000]
            meta = discovery.get("_meta")
            if isinstance(meta, dict) and isinstance(meta.get("io.modelcontextprotocol/serverInfo"), dict):
                self.server_info = meta["io.modelcontextprotocol/serverInfo"]
            return

        try:
            result = self._request(
                "initialize",
                {
                    "protocolVersion": LEGACY_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "NextOrca", "version": "0.8.0"},
                },
            )
        except MCPServerError as exc:
            raise MCPServerError(
                f"MCP server '{self.config.name}' supports neither the modern discovery "
                "flow nor the legacy initialize handshake."
            ) from exc

        version = result.get("protocolVersion")
        if version not in LEGACY_PROTOCOL_VERSIONS:
            raise MCPServerError(
                f"MCP server '{self.config.name}' negotiated unsupported legacy version."
            )
        self.protocol_era = "legacy"
        self.protocol_version = version
        self.server_instructions = str(result.get("instructions", ""))[:4_000]
        info = result.get("serverInfo")
        if isinstance(info, dict):
            self.server_info = info

        self._write_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )

    def list_tools(self) -> list[dict[str, Any]]:
        if self.protocol_era not in {"modern", "legacy"}:
            raise MCPServerError("MCP server must be connected before listing tools.")
        tools: list[dict[str, Any]] = []
        cursor: str | None = None

        for _ in range(20):
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self._request("tools/list", params)
            page = result.get("tools")
            if not isinstance(page, list):
                raise MCPServerError("MCP tools/list response omitted a tools array.")
            for item in page:
                if not isinstance(item, dict):
                    continue
                tools.append(item)
                if len(tools) > MAX_MCP_TOOLS_PER_SERVER:
                    raise MCPServerError(
                        f"MCP server '{self.config.name}' exposed more than "
                        f"{MAX_MCP_TOOLS_PER_SERVER} tools."
                    )
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
            if not isinstance(cursor, str) or len(cursor) > 2_000:
                raise MCPServerError("MCP tools/list returned an invalid pagination cursor.")
        raise MCPServerError("MCP tools/list exceeded the 20-page pagination limit.")

    def call_tool(self, remote_name: str, arguments: dict[str, Any]) -> str:
        params = {"name": remote_name, "arguments": arguments}
        result = self._request("tools/call", params)
        blocks = result.get("content", [])
        if not isinstance(blocks, list):
            blocks = []
        text_parts = [
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            text_parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
        if not text_parts:
            text_parts.append("[MCP tool returned no text content.]")
        response = "\n".join(text_parts)
        if result.get("isError") is True:
            response = "MCP tool reported an error:\n" + response
        return response[:MAX_OUTPUT_CHARS] + (
            "\n[MCP output truncated]" if len(response) > MAX_OUTPUT_CHARS else ""
        )

    def register_tools(self, registry: ToolRegistry) -> int:
        registered = 0
        for remote_tool in self.list_tools():
            remote_name = remote_tool.get("name")
            if (
                not isinstance(remote_name, str)
                or not remote_name
                or len(remote_name) > MAX_TOOL_NAME_LENGTH
            ):
                continue

            raw_schema = remote_tool.get("inputSchema")
            if not isinstance(raw_schema, dict):
                raise MCPServerError(
                    f"MCP tool '{remote_name}' has no valid inputSchema."
                )
            schema_size = len(json.dumps(raw_schema, ensure_ascii=False))
            if schema_size > MAX_TOOL_SCHEMA_CHARS:
                raise MCPServerError(f"MCP tool '{remote_name}' input schema is too large.")
            if raw_schema.get("type", "object") != "object":
                raise MCPServerError(
                    f"MCP tool '{remote_name}' must accept an object input schema."
                )
            _validate_schema_definition(raw_schema, tool_name=remote_name, depth=0)
            properties = raw_schema.get("properties", {})
            required = raw_schema.get("required", [])
            if not isinstance(properties, dict) or not isinstance(required, list):
                raise MCPServerError(f"MCP tool '{remote_name}' has an invalid input schema.")
            for property_name, definition in properties.items():
                if not isinstance(property_name, str) or not isinstance(definition, dict):
                    raise MCPServerError(f"MCP tool '{remote_name}' has an unsupported input schema.")
                if definition.get("type") not in {
                    "string", "integer", "number", "boolean", "object", "array", "null"
                }:
                    raise MCPServerError(
                        f"MCP tool '{remote_name}' uses an unsupported JSON Schema type."
                    )

            sanitized_server = re.sub(r"[^A-Za-z0-9_]", "_", self.config.name.lower())
            sanitized_tool = re.sub(r"[^A-Za-z0-9_]", "_", remote_name.lower())
            internal_name = f"mcp_{sanitized_server}_{sanitized_tool}"
            description = str(remote_tool.get("description", "External MCP tool"))[:2_000]
            namespaced_description = (
                f"MCP server '{self.config.name}' tool '{remote_name}'. {description}"
            )[:2_500]
            schema = dict(raw_schema)
            schema["type"] = "object"
            schema["properties"] = properties
            schema["required"] = required
            schema.setdefault("additionalProperties", False)

            def prepare(
                arguments: dict[str, Any],
                *,
                tool_name: str = remote_name,
                schema_name: str = internal_name,
                tool_schema: dict[str, Any] = schema,
            ) -> PreparedToolOperation:
                _validate_remote_arguments(tool_schema, arguments, tool_name=tool_name)
                preview = (
                    f"External MCP operation: {self.config.name}.{tool_name}\n"
                    f"Model tool name: {schema_name}\n"
                    "Arguments (review before approving):\n"
                    + json.dumps(arguments, ensure_ascii=False, indent=2)[:12_000]
                )
                return PreparedToolOperation(
                    preview=preview,
                    execute=lambda: self.call_tool(tool_name, arguments),
                )

            registry.register(
                ToolSpec(
                    name=internal_name,
                    description=namespaced_description,
                    parameters=schema,
                    handler=lambda _args: "MCP calls must use the approval pipeline.",
                    read_only=False,
                    prepare_handler=prepare,
                )
            )
            registered += 1
        return registered

    def _stop_process(self, *, force: bool = False) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()
            except OSError:
                pass
        if force and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    process.terminate()
                except OSError:
                    pass
        try:
            process.wait(timeout=0.5 if force else 1.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        for stream in (process.stdout, process.stdin):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass
        reader = self._reader
        if reader is not None and reader.is_alive():
            reader.join(timeout=0.5)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._stop_process()
            self.sandbox.close()

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
