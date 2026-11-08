from __future__ import annotations

import json

# ruff: isort: off
import shutil
import sys
from pathlib import Path

import pytest

from nextorca.mcp_stdio import (
    LEGACY_PROTOCOL_VERSION,
    MODERN_PROTOCOL_VERSION,
    MCPServerConfig,
    MCPServerError,
    MCPStdioClient,
    load_mcp_config,
)
from nextorca.tool_registry import ToolExecutionError, ToolRegistry
# ruff: isort: on


MODERN_SERVER = r'''
import json, os, sys

def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "server/discover":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resultType": "complete",
                "supportedVersions": ["2026-07-28"],
                "capabilities": {"tools": {}},
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "modern-test", "version": "1"}}
            }
        })
    elif method == "tools/list":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resultType": "complete",
                "tools": [{
                    "name": "echo-text",
                    "description": "Echo a text value",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string", "minLength": 1}},
                        "required": ["text"],
                        "additionalProperties": False
                    }
                }]
            }
        })
    elif method == "tools/call":
        value = request.get("params", {}).get("arguments", {}).get("text", "")
        # API keys from the parent process are not inherited unless explicitly allowed.
        hidden = " (secret inherited)" if os.environ.get("OPENROUTER_API_KEY") else ""
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resultType": "complete",
                "content": [{"type": "text", "text": value + hidden}]
            }
        })
'''


LEGACY_SERVER = r'''
import json, sys

def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "server/discover":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "Method not found"}
        })
    elif method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "legacy-test", "version": "1"}
            }
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [{
                    "name": "legacy_echo",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"]
                    }
                }]
            }
        })
    elif method == "tools/call":
        value = request.get("params", {}).get("arguments", {}).get("text", "")
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": "legacy: " + value}]}
        })
'''


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("bwrap") is None,
    reason="MCP stdio tests require the Linux Bubblewrap sandbox.",
)


MCP_TEST_PYTHON = "/usr/bin/python3"


def _client(script: str, tmp_path: Path, name: str = "test") -> MCPStdioClient:
    config = MCPServerConfig(
        name=name,
        command=(MCP_TEST_PYTHON, "-u", "-c", script),
        timeout_seconds=3.0,
    )
    return MCPStdioClient(config, workspace_root=tmp_path)


def test_modern_mcp_discovery_lists_and_calls_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "do-not-inherit-to-mcp")
    registry = ToolRegistry()
    with _client(MODERN_SERVER, tmp_path, "modern") as client:
        assert client.protocol_era == "modern"
        assert client.protocol_version == MODERN_PROTOCOL_VERSION
        assert client.server_info["name"] == "modern-test"

        count = client.register_tools(registry)
        assert count == 1
        tool = registry.get("mcp_modern_echo_text")
        assert tool.read_only is False
        prepared = registry.prepare(tool, {"text": "hello"})
        assert prepared is not None
        assert "External MCP operation: modern.echo-text" in prepared.preview
        assert registry.execute_prepared(prepared) == "hello"


def test_legacy_mcp_server_uses_initialize_fallback(tmp_path):
    registry = ToolRegistry()
    with _client(LEGACY_SERVER, tmp_path, "legacy") as client:
        assert client.protocol_era == "legacy"
        assert client.protocol_version == LEGACY_PROTOCOL_VERSION
        assert client.server_info["name"] == "legacy-test"
        assert client.register_tools(registry) == 1
        tool = registry.get("mcp_legacy_legacy_echo")
        prepared = registry.prepare(tool, {"text": "ok"})
        assert prepared is not None
        assert registry.execute_prepared(prepared) == "legacy: ok"


def test_mcp_config_requires_argv_array_and_valid_server_name(tmp_path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps({"servers": [{"name": "bad name", "command": ["echo"]}]}),
        encoding="utf-8",
    )
    with pytest.raises(MCPServerError, match="invalid name"):
        load_mcp_config(config_path)

    config_path.write_text(
        json.dumps({"servers": [{"name": "server", "command": "echo hi"}]}),
        encoding="utf-8",
    )
    with pytest.raises(MCPServerError, match="array of strings"):
        load_mcp_config(config_path)


def test_mcp_config_limits_server_count(tmp_path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps({"servers": [{"name": f"s{i}", "command": ["echo"]} for i in range(9)]}),
        encoding="utf-8",
    )
    with pytest.raises(MCPServerError, match="At most"):
        load_mcp_config(config_path)


def test_mcp_tool_schema_rejects_non_object_arguments(tmp_path):
    script = MODERN_SERVER.replace(
        '"type": "object",\n                        "properties": {"text": {"type": "string", "minLength": 1}},',
        '"type": "array",\n                        "properties": {},',
    )
    with _client(script, tmp_path, "schema") as client, pytest.raises(
        MCPServerError, match="must accept an object"
    ):
        client.list_tools()
        # list_tools returns the server schema; registration validates its shape.
        client.register_tools(ToolRegistry())


def test_mcp_server_process_is_closed_on_context_exit(tmp_path):
    client = _client(MODERN_SERVER, tmp_path, "close")
    with client:
        process = client.process
        assert process is not None and process.poll() is None
    assert process is not None
    assert process.poll() is not None


def test_env_passthrough_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_EXPLICIT_VALUE", "visible")
    config = MCPServerConfig(
        name="explicit",
        command=(MCP_TEST_PYTHON, "-u", "-c", MODERN_SERVER),
        env_passthrough=("MCP_EXPLICIT_VALUE",),
        timeout_seconds=3.0,
    )
    client = MCPStdioClient(
        config, workspace_root=tmp_path
    )
    environment = client._process_environment()
    assert environment["MCP_EXPLICIT_VALUE"] == "visible"
    assert "OPENROUTER_API_KEY" not in environment



def test_modern_input_required_response_is_rejected(tmp_path):
    script = MODERN_SERVER.replace(
        '"resultType": "complete",\n                "tools":',
        '"resultType": "input_required",\n                "tools":',
    )
    client = _client(script, tmp_path, "input-required")
    with client, pytest.raises(MCPServerError, match="interactive protocol input"):
        client.list_tools()


def test_remote_tool_schema_validates_nested_arguments(tmp_path):
    script = MODERN_SERVER.replace(
        '"properties": {"text": {"type": "string", "minLength": 1}},\n'
        '                        "required": ["text"],',
        '"properties": {"nested": {"type": "object", "properties": '
        '{"count": {"type": "integer", "minimum": 1}}, "required": ["count"]}},\n'
        '                        "required": ["nested"],',
    )
    registry = ToolRegistry()
    with _client(script, tmp_path, "nested") as client:
        assert client.register_tools(registry) == 1
        tool = registry.get("mcp_nested_echo_text")
        with pytest.raises(ToolExecutionError, match="below its minimum"):
            registry.prepare(tool, {"nested": {"count": 0}})


def test_mcp_request_timeout_terminates_server_process_group(tmp_path):
    script = r'''
import json, sys, time
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "server/discover":
        result = {
            "resultType": "complete",
            "supportedVersions": ["2026-07-28"],
            "capabilities": {"tools": {}}
        }
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
        sys.stdout.flush()
    elif method == "tools/list":
        time.sleep(5)
'''
    config = MCPServerConfig(
        name="slow",
        command=(MCP_TEST_PYTHON, "-u", "-c", script),
        timeout_seconds=0.5,
    )
    client = MCPStdioClient(
        config, workspace_root=tmp_path
    )
    client.connect()
    process = client.process
    assert process is not None and process.poll() is None
    with pytest.raises(MCPServerError, match="timed out"):
        client.list_tools()
    assert process.poll() is not None
    client.close()


def test_mcp_manifest_network_and_writable_grants_are_typed(tmp_path):
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "isolated",
                        "command": ["python3", "server.py"],
                        "network_access": True,
                        "writable_paths": ["artifacts"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config = load_mcp_config(config_path)[0]
    assert config.network_access is True
    assert config.writable_paths == ("artifacts",)

    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "bad",
                        "command": ["python3", "server.py"],
                        "network_access": "yes",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(MCPServerError, match="network_access must be a boolean"):
        load_mcp_config(config_path)
