from __future__ import annotations

import json

from nextorca import cli
from nextorca.session_store import SQLiteSessionStore


def test_session_cli_commands_run_without_constructing_provider(tmp_path, monkeypatch, capsys):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    session_id = store.create_session(
        workspace=str(workspace.resolve()),
        model="mock",
        session_id="cli-session",
    )
    store.append_message(session_id, {"role": "system", "content": "do not show"})
    store.append_message(session_id, {"role": "user", "content": "Fix the parser regression"})

    def fail_provider(*args, **kwargs):
        raise AssertionError("session commands must not construct a model provider")

    monkeypatch.setattr(cli, "OpenAICompatibleProvider", fail_provider)
    common = ["--workspace", str(workspace), "--session-db", str(store.path)]

    assert cli.main(["sessions", "list", *common]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert len(listed) == 1
    assert listed[0]["session_id"] == session_id
    assert listed[0]["preview"] == "Fix the parser regression"

    assert cli.main(["sessions", "search", "parser", *common]) == 0
    searched = json.loads(capsys.readouterr().out)
    assert len(searched) == 1
    assert searched[0]["session_id"] == session_id

    assert cli.main(["sessions", "show", session_id, *common]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["session_id"] == session_id
    assert shown["message_count"] == 2


def test_session_cli_does_not_reveal_cross_workspace_session(tmp_path, capsys):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    store.create_session(
        workspace=str(tmp_path / "other"),
        model="mock",
        session_id="foreign-session",
    )

    result = cli.main([
        "sessions",
        "show",
        "foreign-session",
        "--workspace",
        str(workspace),
        "--session-db",
        str(store.path),
    ])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "Session not found in this workspace.\n"
