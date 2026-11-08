from __future__ import annotations

import pytest

from nextorca.provider import ProviderUnavailableError
from nextorca.runtime import AgentRuntime
from nextorca.session_store import SQLiteSessionStore
from nextorca.types import AgentEvent, AssistantTurn
from nextorca.workspace import Workspace, build_workspace_tools


class FakeRouteDecision:
    def as_dict(self):
        return {
            "task": "explore",
            "provider": "local",
            "model": "small-model",
            "reason": "read-oriented task",
            "fallback_from": None,
        }


class MetricsProvider:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.last_decision = FakeRouteDecision()

    def complete(self, *, model, messages, tools):
        if self.error:
            raise self.error
        return AssistantTurn(
            content="The project contains a CLI.",
            usage={"input_tokens": 23, "output_tokens": 11},
        )


def test_runtime_persists_route_latency_and_token_metrics(tmp_path):
    workspace = Workspace(tmp_path)
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.sqlite3")
    events: list[AgentEvent] = []
    runtime = AgentRuntime(
        provider=MetricsProvider(),
        model="hybrid",
        tools=build_workspace_tools(workspace),
        session_store=store,
        workspace_root=workspace.root,
        on_event=events.append,
    )

    assert runtime.run("Map the repository structure.") == "The project contains a CLI."
    session_id = runtime.last_session_id
    assert session_id is not None

    metrics = [
        event
        for event in store.load_events(session_id)
        if event["type"] == "model_metrics"
    ]
    assert len(metrics) == 1
    assert metrics[0]["status"] == "success"
    assert metrics[0]["input_tokens"] == 23
    assert metrics[0]["output_tokens"] == 11
    assert metrics[0]["route"]["provider"] == "local"
    assert metrics[0]["latency_ms"] >= 0

    callback_metrics = [event for event in events if event.type == "model_metrics"]
    assert len(callback_metrics) == 1
    assert callback_metrics[0].data["task"] == "explore"

    summary = store.metrics_summary(workspace=str(workspace.root))
    assert summary["request_count"] == 1
    assert summary["success_count"] == 1
    assert summary["input_tokens"] == 23
    assert summary["output_tokens"] == 11
    assert summary["by_provider"]["local"]["requests"] == 1
    assert summary["by_task"] == {"explore": 1}


def test_runtime_records_provider_failure_metrics(tmp_path):
    workspace = Workspace(tmp_path)
    store = SQLiteSessionStore(tmp_path / ".nextorca" / "sessions.sqlite3")
    runtime = AgentRuntime(
        provider=MetricsProvider(error=ProviderUnavailableError("offline")),
        model="hybrid",
        tools=build_workspace_tools(workspace),
        session_store=store,
        workspace_root=workspace.root,
    )

    with pytest.raises(ProviderUnavailableError):
        runtime.run("Map the repository structure.")

    session_id = runtime.last_session_id
    assert session_id is not None
    metrics = [
        event
        for event in store.load_events(session_id)
        if event["type"] == "model_metrics"
    ]
    assert len(metrics) == 1
    assert metrics[0]["status"] == "error"
    assert metrics[0]["error_type"] == "ProviderUnavailableError"
    assert metrics[0]["route"]["provider"] == "local"
    summary = store.metrics_summary(session_id=session_id)
    assert summary["failure_count"] == 1
    assert summary["success_count"] == 0
