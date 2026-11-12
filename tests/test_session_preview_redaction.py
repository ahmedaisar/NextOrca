from __future__ import annotations

import pytest

from nextorca.session_store import SQLiteSessionStore


def _session(store, workspace, session_id, *messages):
    store.create_session(workspace=workspace, model="mock", session_id=session_id)
    for message in messages:
        store.append_message(session_id, message)


def test_list_sessions_is_workspace_scoped_and_returns_bounded_metadata(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo-a")
    other_workspace = str(tmp_path / "repo-b")
    _session(
        store,
        workspace,
        "session-a",
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "First task"},
        {"role": "assistant", "content": "Answer"},
        {"role": "tool", "content": "Tool output"},
        {"role": "user", "content": "Second task with a longer tail"},
    )
    _session(
        store,
        other_workspace,
        "session-b",
        {"role": "system", "content": "Other system."},
        {"role": "user", "content": "Other project task"},
    )

    sessions = store.list_sessions(workspace, limit=10, preview_chars=11)

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "session-a"
    assert sessions[0]["model"] == "mock"
    assert sessions[0]["message_count"] == 5
    assert sessions[0]["last_user_prompt"] == "Second task"
    assert sessions[0]["preview_truncated"] is True
    assert "Tool output" not in str(sessions)


def test_list_sessions_empty_workspace_and_limit_validation(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")

    assert store.list_sessions(str(tmp_path / "empty")) == []
    with pytest.raises(ValueError, match="between 1 and 100"):
        store.list_sessions(str(tmp_path), limit=0)
    with pytest.raises(ValueError, match="preview length"):
        store.list_sessions(str(tmp_path), preview_chars=0)


def test_search_sessions_matches_literal_unicode_and_escapes_like_characters(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo")
    _session(
        store,
        workspace,
        "unicode-session",
        {"role": "system", "content": "Never search system prompts."},
        {"role": "user", "content": r"Find 100%_literal\path in Māuruuru.md"},
        {"role": "tool", "content": "100%_literal tool-only result"},
        {"role": "user", "content": "Another user prompt"},
    )

    matches = store.search_sessions(workspace, r"100%_literal\path")

    assert len(matches) == 1
    assert matches[0]["session_id"] == "unicode-session"
    assert "100%_literal" in matches[0]["excerpt"]
    assert "Māuruuru" in matches[0]["excerpt"]


def test_search_sessions_never_returns_other_workspaces_or_non_user_messages(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo-a")
    _session(
        store,
        workspace,
        "current",
        {"role": "system", "content": "needle in system"},
        {"role": "tool", "content": "needle in tool output"},
        {"role": "user", "content": "No matching prompt"},
    )
    _session(
        store,
        str(tmp_path / "repo-b"),
        "other",
        {"role": "user", "content": "needle in another workspace"},
    )

    assert store.search_sessions(workspace, "needle") == []


def test_search_sessions_enforces_result_limit_and_rejects_invalid_queries(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path)
    _session(
        store,
        workspace,
        "many-matches",
        {"role": "user", "content": "needle first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "needle second"},
    )

    matches = store.search_sessions(workspace, "needle", limit=1)

    assert len(matches) == 1
    with pytest.raises(ValueError, match="query"):
        store.search_sessions(workspace, " ")
    with pytest.raises(ValueError, match="scan limit"):
        store.search_sessions(workspace, "needle", scan_limit=0)


def test_get_session_summary_requires_the_matching_workspace(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo-a")
    _session(
        store,
        workspace,
        "visible",
        {"role": "user", "content": "Summarize this session"},
    )

    summary = store.get_session_summary("visible", workspace=workspace)

    assert summary is not None
    assert summary["message_count"] == 1
    assert summary["last_user_prompt"] == "Summarize this session"
    assert store.get_session_summary("visible", workspace=str(tmp_path / "repo-b")) is None


def test_session_previews_and_search_redact_common_credentials(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path / "repo")
    _session(
        store,
        workspace,
        "credential-session",
        {"role": "user", "content": "Deploy with API_KEY=sk-example-secret-value"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "Use Authorization: Bearer abcdefghijklmnop"},
    )

    listed = store.list_sessions(workspace)
    searched = store.search_sessions(workspace, "Authorization")

    assert "[REDACTED]" in listed[0]["last_user_prompt"]
    assert "abcdefghijklmnop" not in listed[0]["last_user_prompt"]
    assert len(searched) == 1
    assert "[REDACTED]" in searched[0]["excerpt"]
    assert "abcdefghijklmnop" not in searched[0]["excerpt"]

    summary = store.get_session_summary("credential-session", workspace=workspace)
    assert summary is not None
    assert "[REDACTED]" in summary["last_user_prompt"]
