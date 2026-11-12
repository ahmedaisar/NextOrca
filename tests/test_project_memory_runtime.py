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
    source_session_id = store.create_session(workspace=workspace, model="mock")
    store.append_message(source_session_id, {"role": "system", "content": "System instructions."})
    source_sequence = store.append_message(
        source_session_id,
        {"role": "user", "content": "We decided how Redis cache keys should work."},
    )
    record = store.add_project_memory(
        workspace=workspace,
        memory_type="decision",
        content="Redis cache keys include the schema version and expire after five minutes.",
        source_session_id=source_session_id,
        source_message_sequence=source_sequence,
    )
    provider = MemoryProvider()
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=ToolRegistry(),
        session_store=store,
        workspace_root=workspace,
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
    assert f"{source_session_id}#{source_sequence}" in memory_messages[0]["content"]
    assert runtime.session_id != source_session_id
    assert any(event.type == "project_memory_selected" for event in events)
    assert all(
        "Selected project memory" not in message.get("content", "")
        for message in store.load_messages(runtime.session_id)
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


def test_optional_memory_is_dropped_when_it_would_exceed_context_budget(tmp_path):
    from nextorca.runtime import AgentConfig

    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path)
    session_id = store.create_session(workspace=workspace, model="mock")
    store.append_message(session_id, {"role": "system", "content": "System instructions."})
    sequence = store.append_message(session_id, {"role": "user", "content": "Redis context decision."})
    store.add_project_memory(
        workspace=workspace,
        memory_type="fact",
        content="Redis " + ("cache-context " * 120),
        source_session_id=session_id,
        source_message_sequence=sequence,
    )
    runtime = AgentRuntime(
        provider=MemoryProvider(),
        model="mock",
        tools=ToolRegistry(),
        session_store=store,
        workspace_root=workspace,
        session_id=session_id,
        config=AgentConfig(max_context_chars=1_024),
    )
    messages = [
        {"role": "system", "content": "System instructions."},
        {"role": "user", "content": "How do Redis keys work?"},
    ]

    assert runtime._with_project_memory(messages, "How do Redis keys work?") == messages



def test_local_only_router_uses_local_provider_with_project_memory(tmp_path):
    from nextorca.routing import HybridRouter

    class Provider:
        def __init__(self, name):
            self.name = name
            self.messages = []

        def complete(self, *, model, messages, tools):
            self.messages.append(messages)
            return AssistantTurn(content=self.name)

    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path)
    source_session = store.create_session(workspace=workspace, model="mock")
    store.append_message(source_session, {"role": "system", "content": "System"})
    sequence = store.append_message(source_session, {"role": "user", "content": "Cache behavior"})
    store.add_project_memory(
        workspace=workspace,
        memory_type="decision",
        content="Redis cache TTL is five minutes.",
        source_session_id=source_session,
        source_message_sequence=sequence,
    )
    local = Provider("local")
    cloud = Provider("cloud")
    router = HybridRouter(
        local_provider=local,
        local_model="local",
        cloud_provider=cloud,
        cloud_model="cloud",
        privacy_mode="local-only",
    )
    runtime = AgentRuntime(
        provider=router,
        model="hybrid",
        tools=ToolRegistry(),
        session_store=store,
        workspace_root=workspace,
    )

    assert runtime.run("How should Redis cache TTL be configured?") == "local"
    assert len(local.messages) == 1
    assert any(
        "Selected project memory" in message.get("content", "")
        for message in local.messages[0]
    )
    assert cloud.messages == []
