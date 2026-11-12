from __future__ import annotations

from nextorca.repl import run_repl
from nextorca.runtime import AgentRuntime
from nextorca.session_store import SQLiteSessionStore
from nextorca.tool_registry import ToolRegistry


class UnusedProvider:
    def complete(self, *, model, messages, tools):
        raise AssertionError("slash-command tests must not call the provider")


def _runtime(workspace, store):
    return AgentRuntime(
        provider=UnusedProvider(),
        model="mock",
        tools=ToolRegistry(),
        session_store=store,
        workspace_root=workspace,
    )


def test_repl_lists_and_resumes_session_by_index(tmp_path, monkeypatch, capsys):
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    session_id = store.create_session(
        workspace=str(tmp_path.resolve()),
        model="mock",
        session_id="repl-session",
    )
    store.append_message(session_id, {"role": "user", "content": "Continue the unit tests"})
    runtime = _runtime(tmp_path, store)
    inputs = iter(["/sessions", "/resume 1", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    run_repl(runtime)

    output = capsys.readouterr().out
    assert "Continue the unit tests" in output
    assert f"Resumed session {session_id}." in output
    assert runtime.session_id == session_id
    assert runtime.last_session_id == session_id


def test_repl_requires_exact_workspace_session_id_and_does_not_create_on_resume(
    tmp_path,
    monkeypatch,
    capsys,
):
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    store.create_session(
        workspace=str(tmp_path / "other"),
        model="mock",
        session_id="foreign-session",
    )
    runtime = _runtime(tmp_path, store)
    inputs = iter(["/resume foreign-session", "/resume missing-session", "/resume", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    run_repl(runtime)

    output = capsys.readouterr().out
    assert output.count("Session not found in this workspace.") == 2
    assert "Usage: /resume <session-id-or-index>" in output
    assert runtime.session_id is None
    assert store.get_session("missing-session") is None
