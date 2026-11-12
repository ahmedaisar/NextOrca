from __future__ import annotations

import pytest

from nextorca.session_store import SessionStoreError, SQLiteSessionStore


def _source_session(store, workspace, session_id="source-session"):
    store.create_session(workspace=workspace, model="mock", session_id=session_id)
    store.append_message(session_id, {"role": "system", "content": "System"})
    sequence = store.append_message(
        session_id,
        {"role": "user", "content": "We chose a project convention for cache invalidation."},
    )
    return session_id, sequence


def test_project_memory_requires_valid_source_message_and_keeps_provenance(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo")
    session_id, sequence = _source_session(store, workspace)

    record = store.add_project_memory(
        workspace=workspace,
        memory_type="decision",
        content="Use versioned cache keys and a five-minute TTL.",
        source_session_id=session_id,
        source_message_sequence=sequence,
    )

    assert record["memory_type"] == "decision"
    assert record["source_session_id"] == session_id
    assert record["source_message_sequence"] == sequence
    assert record["verification_status"] == "operator_confirmed"
    assert "versioned cache keys" in record["content"]


def test_project_memory_refuses_cross_workspace_or_non_user_sources(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo-a")
    other_workspace = str(tmp_path / "repo-b")
    session_id, sequence = _source_session(store, workspace)

    with pytest.raises(SessionStoreError, match="Source message"):
        store.add_project_memory(
            workspace=other_workspace,
            memory_type="fact",
            content="This must not cross project boundaries.",
            source_session_id=session_id,
            source_message_sequence=sequence,
        )

    store.create_session(workspace=workspace, model="mock", session_id="tool-session")
    store.append_message("tool-session", {"role": "tool", "content": "Tool output"})
    with pytest.raises(ValueError, match="user-authored"):
        store.add_project_memory(
            workspace=workspace,
            memory_type="fact",
            content="A fact from tool output",
            source_session_id="tool-session",
            source_message_sequence=1,
        )


def test_project_memory_rejects_secrets_invalid_types_and_oversized_content(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path)
    session_id, sequence = _source_session(store, workspace)

    with pytest.raises(ValueError, match="credential"):
        store.add_project_memory(
            workspace=workspace,
            memory_type="fact",
            content="Set API_KEY=sk-example-super-secret-token",
            source_session_id=session_id,
            source_message_sequence=sequence,
        )
    with pytest.raises(ValueError, match="Memory type"):
        store.add_project_memory(
            workspace=workspace,
            memory_type="guess",
            content="A project detail",
            source_session_id=session_id,
            source_message_sequence=sequence,
        )
    with pytest.raises(ValueError, match="at most"):
        store.add_project_memory(
            workspace=workspace,
            memory_type="fact",
            content="x" * 2_001,
            source_session_id=session_id,
            source_message_sequence=sequence,
        )


def test_project_memory_list_show_forget_and_workspace_isolation(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo-a")
    other_workspace = str(tmp_path / "repo-b")
    session_id, sequence = _source_session(store, workspace)
    record = store.add_project_memory(
        workspace=workspace,
        memory_type="convention",
        content="Use pytest for tests.",
        source_session_id=session_id,
        source_message_sequence=sequence,
    )

    records = store.list_project_memories(workspace)
    assert [item["memory_id"] for item in records] == [record["memory_id"]]
    assert store.get_project_memory(record["memory_id"], workspace=other_workspace) is None
    assert not store.forget_project_memory(record["memory_id"], workspace=other_workspace)
    assert store.forget_project_memory(record["memory_id"], workspace=workspace)
    assert store.list_project_memories(workspace) == []
    assert store.get_project_memory(record["memory_id"], workspace=workspace) is None


def test_project_memory_retrieval_is_lexical_bounded_and_ranked(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo")
    session_id, sequence = _source_session(store, workspace)
    first = store.add_project_memory(
        workspace=workspace,
        memory_type="decision",
        content="Redis cache invalidation uses versioned keys and a five-minute TTL.",
        source_session_id=session_id,
        source_message_sequence=sequence,
    )
    second = store.add_project_memory(
        workspace=workspace,
        memory_type="command",
        content="Run pytest with uv run pytest tests -q.",
        source_session_id=session_id,
        source_message_sequence=sequence,
    )

    selected = store.search_project_memories(workspace, "Redis cache versioned TTL", limit=1)

    assert len(selected) == 1
    assert selected[0]["memory_id"] == first["memory_id"]
    assert set(selected[0]["match_terms"]) >= {"redis", "cache", "versioned", "ttl"}
    assert store.search_project_memories(workspace, "unrelated deployment framework") == []
    assert second["memory_id"] != first["memory_id"]


def test_project_memory_enable_disable_is_workspace_scoped_and_forget_is_durable(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo-a")
    other_workspace = str(tmp_path / "repo-b")
    session_id, sequence = _source_session(store, workspace)
    record = store.add_project_memory(
        workspace=workspace,
        memory_type="fact",
        content="The service uses Redis for caching.",
        source_session_id=session_id,
        source_message_sequence=sequence,
    )

    assert store.project_memory_enabled(workspace) is True
    store.set_project_memory_enabled(workspace, False)
    assert store.project_memory_enabled(workspace) is False
    assert store.project_memory_enabled(other_workspace) is True
    assert store.search_project_memories(workspace, "Redis caching") == []
    store.set_project_memory_enabled(workspace, True)
    assert len(store.search_project_memories(workspace, "Redis caching")) == 1

    assert store.forget_project_memory(record["memory_id"], workspace=workspace)
    assert store.search_project_memories(workspace, "Redis caching") == []
