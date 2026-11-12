from __future__ import annotations

from typing import Any

from nextorca.runtime import AgentRuntime
from nextorca.session_store import SQLiteSessionStore
from nextorca.tool_registry import ToolRegistry
from nextorca.types import AssistantTurn


class MemoryProvider:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, Any]]] = []

    def complete(self, *, model, messages, tools):
        self.requests.append(list(messages))
        return AssistantTurn(content="Done.")


def test_runtime_injects_only_matching_project_memory_and_does_not_persist_it(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path)
    session_id = store.create_session(workspace=workspace, model="mock")
    store.append_message(session_id, {"role": "system", "content": "System instructions."})
    source_sequence = store.append_message(
        session_id,
        {"role": "user", "content": "We decided how Redis cache keys should work."},
    )
    record = store.add_project_memory(
        workspace=workspace,
        memory_type="decision",
        content="Redis cache keys include the schema version and expire after five minutes.",
        source_session_id=session_id,
        source_message_sequence=source_sequence,
    )
    provider = MemoryProvider()
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=ToolRegistry(),
        session_store=store,
        workspace_root=workspace,
        session_id=session_id,
    )
    events = []
    runtime.on_event = events.append

    assert runtime.run("How should Redis cache keys be built?") == "Done."

    sent = provider.requests[0]
    memory_messages = [
        message for message in sent
        if message.get("role") == "system" and "Selected project memory" in message.get("content", "")
    ]
    assert len(memory_messages) == 1
    assert record["memory_id"] in memory_messages[0]["content"]
    assert "schema version" in memory_messages[0]["content"]
    assert f"{session_id}#{source_sequence}" in memory_messages[0]["content"]
    assert any(event.type == "project_memory_selected" for event in events)
    assert all(
        "Selected project memory" not in message.get("content", "")
        for message in store.load_messages(session_id)
    )


def test_disabled_or_unrelated_project_memory_is_not_added_to_provider_context(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path)
    session_id = store.create_session(workspace=workspace, model="mock")
    store.append_message(session_id, {"role": "system", "content": "System instructions."})
    sequence = store.append_message(session_id, {"role": "user", "content": "Project database note."})
    store.add_project_memory(
        workspace=workspace,
        memory_type="fact",
        content="PostgreSQL uses a dedicated analytics schema.",
        source_session_id=session_id,
        source_message_sequence=sequence,
    )
    provider = MemoryProvider()
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=ToolRegistry(),
        session_store=store,
        workspace_root=workspace,
        session_id=session_id,
    )

    runtime.run("How does PostgreSQL analytics schema work?")
    assert any("Selected project memory" in message.get("content", "") for message in provider.requests[0])

    store.set_project_memory_enabled(workspace, False)
    runtime.run("Explain the terminal theme preference.")
    assert not any("Selected project memory" in message.get("content", "") for message in provider.requests[1])
