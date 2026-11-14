from __future__ import annotations

import json

from nextorca.cli import main
from nextorca.session_store import SQLiteSessionStore


def _source_session(database, workspace):
    store = SQLiteSessionStore(database)
    session_id = store.create_session(workspace=str(workspace), model="mock")
    store.append_message(session_id, {"role": "system", "content": "System"})
    sequence = store.append_message(
        session_id,
        {"role": "user", "content": "We agreed on the Redis cache key design."},
    )
    return session_id, sequence


def _command(*args, database, workspace):
    return main([
        "memory", *args,
        "--workspace", str(workspace),
        "--session-db", str(database),
    ])


def test_memory_cli_add_list_show_search_and_forget_are_workspace_scoped(tmp_path, capsys):
    database = tmp_path / "sessions.db"
    session_id, sequence = _source_session(database, tmp_path)
    other_workspace = tmp_path / "other"
    other_workspace.mkdir()

    added = _command(
        "add", "Redis cache keys include a schema version.",
        "--type", "decision",
        "--source-session", session_id,
        "--source-message", str(sequence),
        database=database,
        workspace=tmp_path,
    )
    assert added == 0
    memory = json.loads(capsys.readouterr().out)
    memory_id = memory["memory_id"]
    assert memory["verification_status"] == "operator_confirmed"

    listed = _command("list", database=database, workspace=tmp_path)
    assert listed == 0
    assert json.loads(capsys.readouterr().out)["memories"][0]["memory_id"] == memory_id

    searched = _command("search", "Redis schema version", database=database, workspace=tmp_path)
    assert searched == 0
    assert json.loads(capsys.readouterr().out)["selected_memories"][0]["memory_id"] == memory_id

    shown = _command("show", memory_id, database=database, workspace=tmp_path)
    assert shown == 0
    assert json.loads(capsys.readouterr().out)["memory_id"] == memory_id

    hidden = _command("show", memory_id, database=database, workspace=other_workspace)
    assert hidden == 1
    assert "not found in this workspace" in capsys.readouterr().err

    forgotten = _command("forget", memory_id, database=database, workspace=tmp_path)
    assert forgotten == 0
    assert _command("list", database=database, workspace=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["memories"] == []


def test_memory_cli_off_on_and_status_work_without_provider_startup(tmp_path, capsys):
    database = tmp_path / "sessions.db"
    _source_session(database, tmp_path)

    assert _command("status", database=database, workspace=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is True

    assert _command("off", database=database, workspace=tmp_path) == 0
    capsys.readouterr()
    assert _command("status", database=database, workspace=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is False

    assert _command("on", database=database, workspace=tmp_path) == 0
    capsys.readouterr()
    assert _command("status", database=database, workspace=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["enabled"] is True
