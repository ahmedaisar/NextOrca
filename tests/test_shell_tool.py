from __future__ import annotations

from nextorca.shell import MAX_TIMEOUT_SECONDS, build_shell_tool
from nextorca.tool_registry import ToolRegistry, ToolValidationError
from nextorca.workspace import Workspace


def test_shell_tool_prepares_reviewable_command_and_runs_in_workspace(tmp_path):
    (tmp_path / "marker.txt").write_text("inside project", encoding="utf-8")
    workspace = Workspace(tmp_path)
    tool = build_shell_tool(workspace)
    registry = ToolRegistry()
    registry.register(tool)

    prepared = registry.prepare(tool, {"command": "pwd && cat marker.txt", "timeout_seconds": 5})

    assert prepared is not None
    assert str(tmp_path) in prepared.preview
    assert "pwd && cat marker.txt" in prepared.preview
    result = registry.execute_prepared(prepared)
    assert str(tmp_path) in result
    assert "inside project" in result
    assert "Exit code: 0" in result


def test_shell_tool_rejects_excessive_timeout(tmp_path):
    workspace = Workspace(tmp_path)
    tool = build_shell_tool(workspace)
    registry = ToolRegistry()

    try:
        registry.prepare(
            tool,
            {"command": "echo unsafe", "timeout_seconds": MAX_TIMEOUT_SECONDS + 1},
        )
    except ValueError as exc:
        assert "cannot exceed" in str(exc)
    else:
        raise AssertionError("excessive shell timeout should be rejected")


def test_shell_tool_rejects_unknown_arguments(tmp_path):
    workspace = Workspace(tmp_path)
    tool = build_shell_tool(workspace)
    registry = ToolRegistry()

    try:
        registry.prepare(tool, {"command": "pwd", "sudo": True})
    except ToolValidationError:
        pass
    else:
        raise AssertionError("unknown shell arguments should be rejected")
