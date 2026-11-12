from __future__ import annotations

import json

import pytest

from nextorca.cli import main
from nextorca.session_store import SQLiteSessionStore


def _create_session(database, workspace):
    store = SQLiteSessionStore(database)
    session_id = store.create_session(workspace=str(workspace), model="mock")
    store.append_message(session_id, {"role": "system", "content": "System"})
    store.append_message(session_id, {"role": "user", "content": "Find my CLI session"})
    return session_id


def test_sessions_list_command_is_offline_and_workspace_scoped(tmp_path, monkeypatch, capsys):
    database = tmp_path / "sessions.db"
    session_id = _create_session(database, tmp_path)
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()
    _create_session(database, other_workspace)

    def unexpected_provider(*args, **kwargs):
        pytest.fail("sessions commands must not construct a model provider")

    monkeypatch.setattr("nextorca.cli.OpenAICompatibleProvider", unexpected_provider)
    code = main([
        "sessions", "list",
        "--workspace", str(tmp_path),
        "--session-db", str(database),
    ])

    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert [item["session_id"] for item in result["sessions"]] == [session_id]


def test_sessions_search_and_show_commands_are_workspace_scoped(tmp_path, capsys):
    database = tmp_path / "sessions.db"
    session_id = _create_session(database, tmp_path)
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()

    search_code = main([
        "sessions", "search", "CLI session",
        "--workspace", str(tmp_path),
        "--session-db", str(database),
    ])
    assert search_code == 0
    matches = json.loads(capsys.readouterr().out)["matches"]
    assert len(matches) == 1
    assert matches[0]["session_id"] == session_id

    show_code = main([
        "sessions", "show", session_id,
        "--workspace", str(tmp_path),
        "--session-db", str(database),
    ])
    assert show_code == 0
    assert json.loads(capsys.readouterr().out)["session_id"] == session_id

    hidden_code = main([
        "sessions", "show", session_id,
        "--workspace", str(other_workspace),
        "--session-db", str(database),
    ])
    assert hidden_code == 1
    assert "not found in this workspace" in capsys.readouterr().err
