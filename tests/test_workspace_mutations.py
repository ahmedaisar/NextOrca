from __future__ import annotations

import io
import re

import pytest

from nextorca.permissions import InteractiveApprovalPolicy
from nextorca.runtime import AgentRuntime
from nextorca.session_store import SQLiteSessionStore
from nextorca.tool_registry import ToolExecutionError
from nextorca.types import AssistantTurn, ToolCall
from nextorca.workspace import Workspace, build_workspace_tools


class FakeProvider:
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)
        self.requests = []

    def complete(self, *, model, messages, tools):
        self.requests.append({"model": model, "messages": list(messages), "tools": tools})
        return self.turns.pop(0)


def _checkpoint_id(result: str) -> str:
    match = re.search(r"Checkpoint ID: ([0-9a-f-]{36})", result)
    assert match is not None
    return match.group(1)


def test_write_edit_tools_are_not_exposed_by_default(tmp_path):
    registry = build_workspace_tools(Workspace(tmp_path))
    names = {tool["function"]["name"] for tool in registry.provider_tools()}
    assert names == {"Read", "Glob", "Grep"}


def test_edit_requires_approval_then_creates_checkpoint_and_undoes(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    workspace = Workspace(tmp_path)
    registry = build_workspace_tools(
        workspace, include_mutations=True, checkpoint_store=store
    )
    spec = registry.get("Edit")
    arguments = {
        "file_path": "app.py",
        "old_string": "value = 1",
        "new_string": "value = 2",
    }
    prepared = registry.prepare(spec, arguments)

    assert prepared is not None
    assert "-value = 1" in prepared.preview
    assert "+value = 2" in prepared.preview
    assert source.read_text(encoding="utf-8") == "value = 1\n"

    approved = InteractiveApprovalPolicy(
        input_fn=lambda _prompt: "yes",
        output=io.StringIO(),
    ).authorize(spec, arguments, preview=prepared.preview)
    assert approved is True

    result = registry.execute_prepared(prepared)
    assert source.read_text(encoding="utf-8") == "value = 2\n"
    checkpoint_id = _checkpoint_id(result)
    assert workspace.list_checkpoints(store)[0]["checkpoint_id"] == checkpoint_id

    undo_result = workspace.undo_checkpoint(checkpoint_id, store)
    assert "Undid checkpoint" in undo_result
    assert source.read_text(encoding="utf-8") == "value = 1\n"


def test_declined_edit_leaves_workspace_unchanged(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    workspace = Workspace(tmp_path)
    registry = build_workspace_tools(
        workspace, include_mutations=True, checkpoint_store=store
    )
    spec = registry.get("Edit")
    args = {"file_path": "app.py", "old_string": "1", "new_string": "2"}
    prepared = registry.prepare(spec, args)
    assert prepared is not None

    policy = InteractiveApprovalPolicy(
        input_fn=lambda _prompt: "n",
        output=io.StringIO(),
    )
    assert policy.authorize(spec, args, preview=prepared.preview) is False
    assert source.read_text(encoding="utf-8") == "value = 1\n"
    assert workspace.list_checkpoints(store) == []


def test_write_creates_new_file_and_undo_removes_it(tmp_path):
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    workspace = Workspace(tmp_path)
    registry = build_workspace_tools(
        workspace, include_mutations=True, checkpoint_store=store
    )
    spec = registry.get("Write")
    args = {"file_path": "src/new.py", "content": "print('hello')\n"}
    prepared = registry.prepare(spec, args)
    assert prepared is not None
    assert not (tmp_path / "src" / "new.py").exists()

    assert InteractiveApprovalPolicy(
        input_fn=lambda _prompt: "y",
        output=io.StringIO(),
    ).authorize(spec, args, preview=prepared.preview)
    result = registry.execute_prepared(prepared)
    new_file = tmp_path / "src" / "new.py"
    assert new_file.read_text(encoding="utf-8") == "print('hello')\n"

    workspace.undo_checkpoint(_checkpoint_id(result), store)
    assert not new_file.exists()


def test_write_requires_explicit_overwrite_for_existing_file(tmp_path):
    (tmp_path / "already.txt").write_text("old", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    registry = build_workspace_tools(
        Workspace(tmp_path), include_mutations=True, checkpoint_store=store
    )
    with pytest.raises(ToolExecutionError, match="overwrite=true"):
        registry.prepare(
            registry.get("Write"),
            {"file_path": "already.txt", "content": "new"},
        )


def test_edit_requires_unique_match_or_replace_all(tmp_path):
    (tmp_path / "repeat.txt").write_text("x x x", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    registry = build_workspace_tools(
        Workspace(tmp_path), include_mutations=True, checkpoint_store=store
    )
    with pytest.raises(ToolExecutionError, match="more than once"):
        registry.prepare(
            registry.get("Edit"),
            {"file_path": "repeat.txt", "old_string": "x", "new_string": "y"},
        )

    prepared = registry.prepare(
        registry.get("Edit"),
        {
            "file_path": "repeat.txt",
            "old_string": "x",
            "new_string": "y",
            "replace_all": True,
        },
    )
    assert prepared is not None


def test_prepared_edit_refuses_if_file_changes_after_diff_preview(tmp_path):
    source = tmp_path / "race.txt"
    source.write_text("before", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    workspace = Workspace(tmp_path)
    registry = build_workspace_tools(
        workspace, include_mutations=True, checkpoint_store=store
    )
    prepared = registry.prepare(
        registry.get("Edit"),
        {"file_path": "race.txt", "old_string": "before", "new_string": "approved"},
    )
    assert prepared is not None
    source.write_text("changed by another process", encoding="utf-8")

    with pytest.raises(ToolExecutionError, match="changed after approval"):
        registry.execute_prepared(prepared)
    assert source.read_text(encoding="utf-8") == "changed by another process"


def test_undo_refuses_to_overwrite_newer_file_changes(tmp_path):
    source = tmp_path / "service.py"
    source.write_text("version = 1\n", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    workspace = Workspace(tmp_path)
    registry = build_workspace_tools(
        workspace, include_mutations=True, checkpoint_store=store
    )
    prepared = registry.prepare(
        registry.get("Edit"),
        {
            "file_path": "service.py",
            "old_string": "version = 1",
            "new_string": "version = 2",
        },
    )
    assert prepared is not None
    result = registry.execute_prepared(prepared)
    source.write_text("version = 3\n", encoding="utf-8")

    with pytest.raises(ToolExecutionError, match="changed since this checkpoint"):
        workspace.undo_checkpoint(_checkpoint_id(result), store)
    assert source.read_text(encoding="utf-8") == "version = 3\n"


def test_agent_runtime_uses_interactive_approval_for_mutation_tool(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("answer = 41\n", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    workspace = Workspace(tmp_path)
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=(
                    ToolCall(
                        id="edit-call",
                        name="Edit",
                        arguments={
                            "file_path": "main.py",
                            "old_string": "41",
                            "new_string": "42",
                        },
                    ),
                )
            ),
            AssistantTurn(content="Updated answer to 42."),
        ]
    )
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=build_workspace_tools(
            workspace, include_mutations=True, checkpoint_store=store
        ),
        permission_policy=InteractiveApprovalPolicy(
            input_fn=lambda _prompt: "y",
            output=io.StringIO(),
        ),
        session_store=store,
        workspace_root=workspace.root,
    )

    assert runtime.run("Update the answer.") == "Updated answer to 42."
    assert source.read_text(encoding="utf-8") == "answer = 42\n"
    assert len(workspace.list_checkpoints(store)) == 1
