from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nextorca.runtime import AgentConfig, AgentRuntime, AgentRuntimeError
from nextorca.tool_registry import ToolRegistry, ToolSpec, ToolValidationError
from nextorca.types import AssistantTurn, ToolCall
from nextorca.workspace import Workspace, build_workspace_tools


class FakeProvider:
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def complete(self, *, model, messages, tools):
        self.requests.append({"model": model, "messages": list(messages), "tools": tools})
        if not self.turns:
            raise AssertionError("Fake provider ran out of responses.")
        return self.turns.pop(0)


def test_agent_loop_executes_read_tool_then_returns_final_answer(tmp_path):
    (tmp_path / "README.md").write_text("NextOrca runtime", encoding="utf-8")
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=(
                    ToolCall(
                        id="call-read-1",
                        name="Read",
                        arguments={"file_path": "README.md"},
                    ),
                )
            ),
            AssistantTurn(content="The workspace README says NextOrca runtime."),
        ]
    )
    events = []
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=build_workspace_tools(Workspace(tmp_path)),
        on_event=events.append,
    )

    answer = runtime.run("What is in the README?")

    assert answer == "The workspace README says NextOrca runtime."
    assert provider.requests[0]["tools"]
    tool_messages = [
        message
        for message in provider.requests[1]["messages"]
        if message.get("role") == "tool"
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call-read-1"
    assert tool_messages[0]["content"] == "NextOrca runtime"
    assert any(event.type == "tool_completed" for event in events)


def test_read_only_policy_denies_registered_mutating_tool(tmp_path):
    invoked = False

    def mutate(_args):
        nonlocal invoked
        invoked = True
        return "changed"

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="Write",
            description="Write something.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=mutate,
            read_only=False,
        )
    )
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=(
                    ToolCall(id="call-write", name="Write", arguments={"path": "x"}),
                )
            ),
            AssistantTurn(content="I cannot make changes in read-only mode."),
        ]
    )
    runtime = AgentRuntime(provider=provider, model="mock", tools=registry)

    answer = runtime.run("Write a file.")

    assert "read-only" in answer
    assert invoked is False
    tool_result = next(
        m for m in provider.requests[1]["messages"] if m.get("role") == "tool"
    )
    assert "Permission denied" in tool_result["content"]


def test_max_turn_budget_is_enforced(tmp_path):
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=(
                    ToolCall(id="c1", name="Glob", arguments={"pattern": "**/*.py"}),
                )
            )
        ]
    )
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=build_workspace_tools(Workspace(tmp_path)),
        config=AgentConfig(max_turns=1),
    )
    with pytest.raises(AgentRuntimeError, match="did not finish"):
        runtime.run("List python files.")


def test_max_tool_calls_is_enforced(tmp_path):
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=(
                    ToolCall(id="c1", name="Glob", arguments={"pattern": "**/*.py"}),
                    ToolCall(id="c2", name="Glob", arguments={"pattern": "**/*.md"}),
                )
            )
        ]
    )
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=build_workspace_tools(Workspace(tmp_path)),
        config=AgentConfig(max_tool_calls=1),
    )
    with pytest.raises(AgentRuntimeError, match="tool-call budget"):
        runtime.run("List files.")


def test_tool_validation_rejects_unknown_fields(tmp_path):
    registry = build_workspace_tools(Workspace(tmp_path))
    with pytest.raises(ToolValidationError, match="Unsupported arguments"):
        registry.execute("Read", {"file_path": "a.py", "command": "whoami"})


def test_workspace_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-external"
    outside.mkdir()
    (outside / "secret.txt").write_text("should not leak", encoding="utf-8")
    (tmp_path / "external").symlink_to(outside, target_is_directory=True)

    registry = build_workspace_tools(Workspace(tmp_path))
    with pytest.raises(Exception, match="WorkspaceError"):
        registry.execute("Read", {"file_path": "external/secret.txt"})


def test_agent_requires_non_empty_prompt(tmp_path):
    runtime = AgentRuntime(
        provider=FakeProvider([AssistantTurn(content="unused")]),
        model="mock",
        tools=build_workspace_tools(Workspace(tmp_path)),
    )
    with pytest.raises(ValueError, match="non-empty"):
        runtime.run("   ")
