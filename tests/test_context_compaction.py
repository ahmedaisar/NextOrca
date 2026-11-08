from __future__ import annotations

from typing import Any

import pytest

from nextorca.runtime import AgentConfig, AgentRuntime
from nextorca.session_store import SQLiteSessionStore
from nextorca.tool_registry import ToolRegistry
from nextorca.types import AssistantTurn


class FakeProvider:
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def complete(self, *, model, messages, tools):
        self.requests.append({"model": model, "messages": list(messages), "tools": tools})
        if not self.turns:
            raise AssertionError("Fake provider ran out of responses.")
        return self.turns.pop(0)


def test_compaction_summarizes_history_without_rewriting_transcript(tmp_path):
    provider = FakeProvider(
        [
            AssistantTurn(content="First answer."),
            AssistantTurn(content="Second answer."),
            AssistantTurn(content="Objective: fix the parser. Decision: preserve the public API."),
            AssistantTurn(content="Continued with the parser fix."),
        ]
    )
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=ToolRegistry(),
        session_store=store,
        workspace_root=tmp_path,
        config=AgentConfig(preserve_recent_messages=2),
    )

    runtime.run("Investigate the parser.")
    runtime.run("Keep the public API stable.")
    session_id = runtime.session_id
    original = store.load_messages(session_id)

    compacted = runtime.compact()

    assert "preserve the public API" in compacted["summary"]
    assert len(store.load_messages(session_id)) == len(original)
    assert runtime.context_status()["last_compaction"]["through_message_count"] == len(original)

    runtime.run("Continue the parser fix.")
    provider_messages = provider.requests[3]["messages"]
    assert provider_messages[0]["role"] == "system"
    assert "Conversation summary from an earlier context compaction" in provider_messages[1]["content"]
    assert "Objective: fix the parser" in provider_messages[1]["content"]
    assert not any(
        message.get("content") == "Investigate the parser."
        for message in provider_messages
    )
    assert any(
        message.get("content") == "Keep the public API stable."
        for message in provider_messages
    )
    assert any(
        message.get("content") == "Continue the parser fix."
        for message in provider_messages
    )
    assert any(
        message.get("content") == "Investigate the parser."
        for message in store.load_messages(session_id)
    )


def test_compaction_preserves_tool_call_and_result_pair(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    runtime = AgentRuntime(
        provider=FakeProvider([AssistantTurn(content="unused")]),
        model="mock",
        tools=ToolRegistry(),
        session_store=store,
        workspace_root=tmp_path,
        config=AgentConfig(preserve_recent_messages=1),
    )
    session_id = store.create_session(workspace=str(tmp_path), model="mock")
    runtime.session_id = session_id
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "old"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "Read", "content": "file"},
    ]
    for message in messages:
        store.append_message(session_id, message)
    store.append_event(
        session_id,
        "context_compaction",
        {
            "summary": "Old task summary.",
            "through_message_count": 4,
            "preserve_recent_messages": 1,
        },
    )

    restored = runtime._apply_compaction(session_id, store.load_messages(session_id))

    assert restored[0]["role"] == "system"
    assert "Old task summary." in restored[1]["content"]
    assert restored[2]["role"] == "assistant"
    assert restored[2]["tool_calls"][0]["id"] == "c1"
    assert restored[3]["role"] == "tool"
    assert restored[3]["tool_call_id"] == "c1"


def test_compaction_requires_an_existing_session(tmp_path):
    runtime = AgentRuntime(
        provider=FakeProvider([AssistantTurn(content="unused")]),
        model="mock",
        tools=ToolRegistry(),
    )
    with pytest.raises(ValueError, match="active persistent session"):
        runtime.compact()
