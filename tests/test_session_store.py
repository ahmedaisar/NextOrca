from __future__ import annotations

import os
import sqlite3
import stat

import pytest

from nextorca.session_store import SessionStoreError, SQLiteSessionStore


def test_session_store_persists_messages_and_events(tmp_path):
    database = tmp_path / ".nextorca" / "sessions.sqlite3"
    store = SQLiteSessionStore(database)
    session_id = store.create_session(workspace=str(tmp_path), model="mock")
    store.append_message(session_id, {"role": "system", "content": "System"})
    store.append_message(session_id, {"role": "user", "content": "Question"})
    store.append_event(session_id, "context_pruned", {"pruned_messages": 2})

    assert store.load_messages(session_id) == [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Question"},
    ]
    assert store.load_events(session_id) == [
        {"type": "context_pruned", "pruned_messages": 2}
    ]
    metadata = store.get_session(session_id)
    assert metadata is not None
    assert metadata["workspace"] == str(tmp_path)
    assert metadata["model"] == "mock"


def test_session_store_refuses_resume_from_different_workspace(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    session_id = store.create_session(workspace=str(tmp_path / "repo-a"), model="mock")
    with pytest.raises(SessionStoreError, match="different workspace"):
        store.ensure_session(
            session_id,
            workspace=str(tmp_path / "repo-b"),
            model="mock",
        )


def test_session_store_rejects_duplicate_session_ids(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    store.create_session(workspace=str(tmp_path), model="mock", session_id="stable-id")
    with pytest.raises(SessionStoreError, match="already exists"):
        store.create_session(workspace=str(tmp_path), model="mock", session_id="stable-id")


def test_session_database_file_is_private_on_posix(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX file mode bits are not available on Windows.")
    path = tmp_path / ".nextorca" / "sessions.db"
    SQLiteSessionStore(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_session_store_rejects_symlink_database(tmp_path):
    target = tmp_path / "target.db"
    target.touch()
    link = tmp_path / "link.db"
    link.symlink_to(target)
    with pytest.raises(SessionStoreError, match="symlink"):
        SQLiteSessionStore(link)



def test_list_sessions_is_workspace_scoped_and_returns_bounded_user_preview(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo")
    other_workspace = str(tmp_path / "other")
    older = store.create_session(workspace=workspace, model="local", session_id="older")
    newer = store.create_session(workspace=workspace, model="cloud", session_id="newer")
    hidden = store.create_session(workspace=other_workspace, model="mock", session_id="other")

    for session_id in (older, newer, hidden):
        store.append_message(session_id, {"role": "system", "content": "private system prompt"})
        store.append_message(session_id, {"role": "tool", "content": "tool output must not be previewed"})
    store.append_message(older, {"role": "user", "content": "older user prompt"})
    store.append_message(newer, {"role": "user", "content": "最新のユーザー質問"})
    store.append_message(hidden, {"role": "user", "content": "other workspace prompt"})

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE sessions SET updated_at = '2026-01-01 00:00:00' WHERE session_id = ?",
            (older,),
        )
        connection.execute(
            "UPDATE sessions SET updated_at = '2026-01-02 00:00:00' WHERE session_id = ?",
            (newer,),
        )

    results = store.list_sessions(workspace, limit=10)

    assert [item["session_id"] for item in results] == [newer, older]
    assert results[0]["message_count"] == 3
    assert results[0]["preview"] == "最新のユーザー質問"
    assert "private system prompt" not in results[0]["preview"]
    assert "tool output" not in results[0]["preview"]
    assert results[0]["workspace"] == workspace
    assert store.list_sessions(workspace, limit=1)[0]["session_id"] == newer


def test_session_overview_hides_sessions_from_other_workspaces(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    session_id = store.create_session(
        workspace=str(tmp_path / "repo"),
        model="mock",
        session_id="private-session",
    )
    store.append_message(session_id, {"role": "user", "content": "hello"})

    assert store.get_session_overview(
        session_id,
        workspace=str(tmp_path / "repo"),
    )["preview"] == "hello"
    assert store.get_session_overview(
        session_id,
        workspace=str(tmp_path / "other"),
    ) is None


def test_search_sessions_uses_literal_user_text_and_workspace_scope(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo")
    current = store.create_session(workspace=workspace, model="mock")
    other = store.create_session(workspace=str(tmp_path / "other"), model="mock")
    store.append_message(current, {"role": "system", "content": "literal %_café must not match here"})
    store.append_message(current, {"role": "tool", "content": "literal %_café in a tool result"})
    store.append_message(current, {"role": "user", "content": "Please inspect literal %_café in config."})
    store.append_message(other, {"role": "user", "content": "literal %_café in another workspace"})

    results = store.search_sessions(workspace, "%_café", limit=10)

    assert len(results) == 1
    assert results[0]["session_id"] == current
    assert results[0]["sequence"] == 3
    assert "%_café" in results[0]["excerpt"]
    assert len(results[0]["excerpt"]) <= 200


def test_search_sessions_caps_results_and_rejects_invalid_bounds(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path)
    session_id = store.create_session(workspace=workspace, model="mock")
    for prompt in ("needle one", "needle two", "needle three"):
        store.append_message(session_id, {"role": "user", "content": prompt})

    assert len(store.search_sessions(workspace, "needle", limit=2)) == 2
    with pytest.raises(SessionStoreError, match="1–50"):
        store.search_sessions(workspace, "needle", limit=51)
    with pytest.raises(SessionStoreError, match="1–500"):
        store.search_sessions(workspace, " " * 501)



def test_session_previews_and_search_redact_common_secrets_and_terminal_controls(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path)
    session_id = store.create_session(workspace=workspace, model="mock")
    prompt = "Review api_key=very-secret-value and authorization: Bearer bearer-secret-value " \
        "plus sk-12345678901234567890\x1b[31m now"
    store.append_message(session_id, {"role": "user", "content": prompt})

    listed = store.list_sessions(workspace)
    searched = store.search_sessions(workspace, "api_key")

    for text in (listed[0]["preview"], searched[0]["excerpt"]):
        assert "very-secret-value" not in text
        assert "bearer-secret-value" not in text
        assert "sk-12345678901234567890" not in text
        assert "\x1b" not in text
        assert "[REDACTED]" in text
