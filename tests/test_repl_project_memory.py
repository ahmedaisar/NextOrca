from __future__ import annotations

from types import SimpleNamespace

from nextorca.repl import _memory_command
from nextorca.session_store import SQLiteSessionStore


def _runtime(tmp_path):
    database = tmp_path / "sessions.db"
    store = SQLiteSessionStore(database)
    workspace = str(tmp_path)
    session_id = store.create_session(workspace=workspace, model="mock")
    store.append_message(session_id, {"role": "system", "content": "System"})
    sequence = store.append_message(
        session_id,
        {"role": "user", "content": "We chose a release branch convention."},
    )
    runtime = SimpleNamespace(session_store=store, workspace_root=workspace)
    return runtime, session_id, sequence


def test_repl_memory_commands_add_list_search_show_forget_and_toggle(tmp_path):
    runtime, session_id, sequence = _runtime(tmp_path)
    added = _memory_command(
        runtime,
        f'add convention {session_id} {sequence} "Release branches use feat slash prefix."',
    )
    memory_id = added.split()[-1]
    assert "Project memory is ON" in _memory_command(runtime, "status")

    assert memory_id in _memory_command(runtime, "list")
    assert memory_id in _memory_command(runtime, "search release branches")
    assert memory_id in _memory_command(runtime, "preview release branches")
    assert "feat slash prefix" in _memory_command(runtime, f"show {memory_id}")

    assert _memory_command(runtime, "off").endswith("disabled for this workspace.")
    assert _memory_command(runtime, "search release branches") == "No matching project memories selected."
    assert _memory_command(runtime, "on").endswith("enabled for this workspace.")
    assert _memory_command(runtime, f"forget {memory_id}").endswith(f"Forgot project memory {memory_id}.")
    assert _memory_command(runtime, "list") == "No project memory records."
