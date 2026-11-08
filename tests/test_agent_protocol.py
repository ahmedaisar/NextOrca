import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "agent_protocol.py"
SPEC = importlib.util.spec_from_file_location("agent_protocol", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ToolCallParseError = MODULE.ToolCallParseError
build_anthropic_content = MODULE.build_anthropic_content
openai_to_anthropic_response = MODULE.openai_to_anthropic_response
parse_tool_calls = MODULE.parse_tool_calls


def _tool(name: str, arguments: dict) -> str:
    import json

    return f"<tool_call>{json.dumps({'name': name, 'arguments': arguments})}</tool_call>"


def test_plain_text_is_preserved(tmp_path):
    assert parse_tool_calls("hello", tmp_path) == ("hello", [])


def test_read_tool_is_converted_to_workspace_absolute_path(tmp_path):
    rest, calls = parse_tool_calls(
        _tool("Read", {"file_path": "src/module.py"}), tmp_path
    )
    assert rest == ""
    assert calls[0]["name"] == "Read"
    assert calls[0]["input"]["file_path"] == str(tmp_path / "src/module.py")
    assert calls[0]["type"] == "tool_use"


@pytest.mark.parametrize(
    ("name", "arguments", "expected_tool"),
    [
        ("Glob", {"pattern": "**/*.py"}, "Glob"),
        ("Grep", {"pattern": "TODO", "glob": "*.py"}, "Grep"),
    ],
)
def test_search_tools_default_to_workspace_root(tmp_path, name, arguments, expected_tool):
    _, calls = parse_tool_calls(_tool(name, arguments), tmp_path)
    assert calls[0]["name"] == expected_tool
    assert calls[0]["input"]["path"] == str(tmp_path)


@pytest.mark.parametrize("name", ["Bash", "Write", "Edit", "Task", "Unknown"])
def test_mutating_shell_and_unknown_tools_are_rejected(tmp_path, name):
    with pytest.raises(ToolCallParseError, match="not permitted"):
        parse_tool_calls(_tool(name, {"command": "rm -rf ."}), tmp_path)


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("Read", {"file_path": "../outside.txt"}),
        ("Read", {"file_path": "/etc/passwd"}),
        ("Glob", {"pattern": "../**/*.py"}),
        ("Glob", {"pattern": "**/*.py", "path": "../"}),
        ("Grep", {"pattern": "secret", "path": "../../etc"}),
        ("Grep", {"pattern": "secret", "glob": "../**/*"}),
    ],
)
def test_path_traversal_and_absolute_escape_are_rejected(tmp_path, name, arguments):
    with pytest.raises(ToolCallParseError, match="workspace|traverse"):
        parse_tool_calls(_tool(name, arguments), tmp_path)


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = tmp_path / "external"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ToolCallParseError, match="workspace"):
        parse_tool_calls(_tool("Read", {"file_path": "external/secret.txt"}), tmp_path)


def test_unclosed_tool_marker_is_rejected(tmp_path):
    with pytest.raises(ToolCallParseError, match="Unterminated"):
        parse_tool_calls("answer <tool_call>{bad}", tmp_path)


@pytest.mark.parametrize(
    "arguments",
    [
        {"file_path": ""},
        {"file_path": "inside.py", "unexpected": "value"},
        {"file_path": "inside.py", "offset": True},
    ],
)
def test_read_schema_is_strict(tmp_path, arguments):
    with pytest.raises(ToolCallParseError):
        parse_tool_calls(_tool("Read", arguments), tmp_path)


def test_content_stop_reason_reflects_tool_call(tmp_path):
    content, reason = build_anthropic_content(
        _tool("Grep", {"pattern": "TODO"}), tmp_path
    )
    assert content[0]["type"] == "tool_use"
    assert reason == "tool_use"
    assert content[0]["input"]["path"] == str(tmp_path)


def test_local_response_preserves_usage_and_model(tmp_path):
    result = openai_to_anthropic_response(
        {
            "model": "local-test",
            "choices": [{"message": {"content": "Done"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        },
        workspace_root=tmp_path,
    )
    assert result["model"] == "local-test"
    assert result["content"] == [{"type": "text", "text": "Done"}]
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 5}


def test_local_response_rejects_disallowed_tool(tmp_path):
    result = {
        "model": "local-test",
        "choices": [{"message": {"content": _tool("Bash", {"command": "pwd"})}}],
    }
    with pytest.raises(ToolCallParseError):
        openai_to_anthropic_response(result, workspace_root=tmp_path)


def test_missing_provider_choice_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="missing choices"):
        openai_to_anthropic_response({}, workspace_root=tmp_path)
