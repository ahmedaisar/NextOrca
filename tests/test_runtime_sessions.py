from __future__ import annotations

from nextorca.runtime import AgentRuntime
from nextorca.session_store import SQLiteSessionStore
from nextorca.types import AssistantTurn
from nextorca.workspace import Workspace, build_workspace_tools


class RecordingProvider:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests = []

    def complete(self, *, model, messages, tools):
        self.requests.append(
            {"model": model, "messages": list(messages), "tools": tools}
        )
        return AssistantTurn(content=self.answer)


def test_agent_runtime_resumes_a_persistent_session(tmp_path):
    workspace = Workspace(tmp_path)
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    first_provider = RecordingProvider("First answer.")
    first_runtime = AgentRuntime(
        provider=first_provider,
        model="mock",
        tools=build_workspace_tools(workspace),
        session_store=store,
        workspace_root=workspace.root,
    )

    assert first_runtime.run("First question?") == "First answer."
    session_id = first_runtime.last_session_id
    assert session_id is not None

    second_provider = RecordingProvider("Follow-up answer.")
    second_runtime = AgentRuntime(
        provider=second_provider,
        model="mock",
        tools=build_workspace_tools(workspace),
        session_store=store,
        workspace_root=workspace.root,
    )
    assert second_runtime.run("Follow-up question?", session_id=session_id) == "Follow-up answer."

    messages = second_provider.requests[0]["messages"]
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert messages[1]["content"] == "First question?"
    assert messages[2]["content"] == "First answer."
    assert messages[3]["content"] == "Follow-up question?"
    assert second_runtime.last_session_id == session_id


def test_runtime_records_context_pruning_checkpoint(tmp_path):
    workspace = Workspace(tmp_path)
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.db")
    session_id = store.create_session(workspace=str(workspace.root), model="mock")
    store.append_message(session_id, {"role": "system", "content": "System prompt."})
    for index in range(12):
        store.append_message(
            session_id,
            {
                "role": "tool",
                "tool_call_id": f"old-{index}",
                "content": f"old result {index} " + "x" * 400,
            },
        )

    provider = RecordingProvider("Compacted context received.")
    runtime = AgentRuntime(
        provider=provider,
        model="mock",
        tools=build_workspace_tools(workspace),
        session_store=store,
        workspace_root=workspace.root,
        config=__import__("nextorca.runtime", fromlist=["AgentConfig"]).AgentConfig(
            max_context_chars=2_500,
            preserve_recent_messages=2,
        ),
    )

    answer = runtime.run("Summarize the current context.", session_id=session_id)

    assert answer == "Compacted context received."
    assert any(
        "[Earlier tool output omitted" in str(message.get("content", ""))
        for message in provider.requests[0]["messages"]
    )
    assert any(
        event["type"] == "context_pruned"
        for event in store.load_events(session_id)
    )
