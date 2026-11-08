from __future__ import annotations

import os
import stat

import pytest

from nextorca.session_store import SQLiteSessionStore, SessionStoreError


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
