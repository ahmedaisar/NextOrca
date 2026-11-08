from __future__ import annotations

import io
from typing import Any

from nextorca.permissions import InteractiveApprovalPolicy
from nextorca.runtime import AgentRuntime
from nextorca.session_store import SQLiteSessionStore
from nextorca.shell import build_shell_tool
from nextorca.types import AssistantTurn, ToolCall
from nextorca.workspace import Workspace, build_workspace_tools


class ScriptedProvider:
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def complete(self, *, model, messages, tools):
        self.requests.append({"model": model, "messages": list(messages), "tools": tools})
        if not self.turns:
            raise AssertionError("Scripted provider ran out of turns.")
        return self.turns.pop(0)


def _call(identifier: str, name: str, arguments: dict[str, Any]) -> AssistantTurn:
    return AssistantTurn(
        tool_calls=(ToolCall(id=identifier, name=name, arguments=arguments),)
    )


def test_terminal_coding_workflow_reads_edits_runs_and_persists(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("print('before')\n", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    workspace = Workspace(tmp_path)
    tools = build_workspace_tools(
        workspace,
        include_mutations=True,
        checkpoint_store=store,
    )
    tools.register(build_shell_tool(workspace))
    answers = iter(["yes", "yes"])
    approval = InteractiveApprovalPolicy(
        input_fn=lambda _prompt: next(answers),
        output=io.StringIO(),
    )
    provider = ScriptedProvider(
        [
            _call("read-1", "Read", {"file_path": "app.py"}),
            _call(
                "edit-1",
                "Edit",
                {
                    "file_path": "app.py",
                    "old_string": "before",
                    "new_string": "after",
                },
            ),
            _call(
                "shell-1",
                "Shell",
                {
                    "command": "python -c \"print('check-ok')\"",
                    "timeout_seconds": 5,
                },
            ),
            AssistantTurn(content="Updated app.py and verified the command output."),
        ]
    )
    runtime = AgentRuntime(
        provider=provider,
        model="scripted",
        tools=tools,
        permission_policy=approval,
        session_store=store,
        workspace_root=tmp_path,
    )

    answer = runtime.run("Change the output and run a quick verification command.")

    assert "verified" in answer
    assert source.read_text(encoding="utf-8") == "print('after')\n"
    assert "check-ok" in str(provider.requests[3]["messages"])
    assert runtime.last_session_id is not None
    assert len(store.load_messages(runtime.last_session_id)) >= 8
    assert workspace.list_checkpoints(store)
