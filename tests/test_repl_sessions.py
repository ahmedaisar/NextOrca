from __future__ import annotations

from types import SimpleNamespace

import pytest

from nextorca.repl import _resume_session


class FakeSessionStore:
    def __init__(self, sessions):
        self.sessions = sessions

    def list_sessions(self, workspace, *, limit):
        return self.sessions[:limit]

    def get_session(self, session_id):
        return next((item for item in self.sessions if item["session_id"] == session_id), None)


def _runtime():
    sessions = [
        {"session_id": "session-one", "workspace": "/repo"},
        {"session_id": "session-two", "workspace": "/repo"},
    ]
    return SimpleNamespace(
        session_store=FakeSessionStore(sessions),
        workspace_root="/repo",
        session_id=None,
        last_session_id=None,
    )


def test_resume_selects_exact_session_id():
    runtime = _runtime()

    assert _resume_session(runtime, "session-two") == "session-two"
    assert runtime.session_id == "session-two"
    assert runtime.last_session_id == "session-two"


def test_resume_selects_recent_session_by_one_based_index():
    runtime = _runtime()

    assert _resume_session(runtime, "1") == "session-one"


@pytest.mark.parametrize("selection", ["unknown", "0", "3", "session"])
def test_resume_rejects_unknown_or_non_exact_selection(selection):
    runtime = _runtime()

    with pytest.raises(ValueError, match="No session matched"):
        _resume_session(runtime, selection)


def test_resume_rechecks_workspace_before_switching():
    runtime = _runtime()
    runtime.session_store.sessions[0]["workspace"] = "/other"

    with pytest.raises(ValueError, match="no longer available"):
        _resume_session(runtime, "session-one")

    assert runtime.session_id is None
