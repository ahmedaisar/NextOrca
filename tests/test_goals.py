from __future__ import annotations

import io
from typing import Any

from nextorca.goals import GoalRunner
from nextorca.permissions import InteractiveApprovalPolicy
from nextorca.runtime import AgentRuntime
from nextorca.session_store import SQLiteSessionStore
from nextorca.shell import build_shell_tool
from nextorca.tool_registry import ToolRegistry
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


def _done():
    return AssistantTurn(
        tool_calls=(ToolCall(id="goal-done", name="GoalDone", arguments={}),)
    )


def test_goal_requires_done_signal_and_independent_approval(tmp_path):
    provider = FakeProvider(
        [
            _done(),
            AssistantTurn(content="Implemented the requested change."),
            AssistantTurn(content="Inspected the repository.\nVERDICT: APPROVE"),
        ]
    )
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    workspace = Workspace(tmp_path)
    registry = build_workspace_tools(workspace)
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=registry,
        session_store=store,
        workspace_root=tmp_path,
    )

    result = GoalRunner(runtime).run("Add the requested feature")

    assert "independently approved" in result
    assert GoalRunner(runtime).status()["status"] == "completed"
    assert "GoalDone" not in registry.names
    assert any(
        item["function"]["name"] == "GoalDone"
        for item in provider.requests[0]["tools"]
    )
    assert any(
        item["function"]["name"] == "GitDiff"
        for item in provider.requests[2]["tools"]
    )


def test_reviewer_feedback_is_sent_back_to_worker(tmp_path):
    provider = FakeProvider(
        [
            _done(),
            AssistantTurn(content="First attempt."),
            AssistantTurn(content="Missing a regression test.\nVERDICT: REVISE"),
            _done(),
            AssistantTurn(content="Added the regression test."),
            AssistantTurn(content="The change is complete.\nVERDICT: APPROVE"),
        ]
    )
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=build_workspace_tools(Workspace(tmp_path)),
        session_store=store,
        workspace_root=tmp_path,
    )

    result = GoalRunner(runtime, max_iterations=2).run("Fix the bug and add a test")

    assert "after 2 attempt(s)" in result
    second_worker_messages = provider.requests[3]["messages"]
    assert any(
        "Missing a regression test" in str(message.get("content", ""))
        for message in second_worker_messages
    )


def test_goal_verification_command_requires_approval(tmp_path):
    provider = FakeProvider(
        [
            _done(),
            AssistantTurn(content="Implementation complete."),
            AssistantTurn(content="Verification output is clean.\nVERDICT: APPROVE"),
        ]
    )
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    workspace = Workspace(tmp_path)
    registry = build_workspace_tools(workspace)
    registry.register(build_shell_tool(workspace))
    approval = InteractiveApprovalPolicy(input_fn=lambda _prompt: "yes", output=io.StringIO())
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=registry,
        permission_policy=approval,
        session_store=store,
        workspace_root=tmp_path,
    )

    result = GoalRunner(runtime).run(
        "Check the project",
        verify_command="python -c \"print('verified')\"",
    )

    assert "Exit code: 0" in result
    assert GoalRunner(runtime).status()["status"] == "completed"


def test_tool_registry_can_remove_temporary_tools():
    registry = ToolRegistry()
    from nextorca.goals import _goal_done_tool

    registry.register(_goal_done_tool(lambda: "done"))
    assert "GoalDone" in registry.names
    registry.unregister("GoalDone")
    assert "GoalDone" not in registry.names
