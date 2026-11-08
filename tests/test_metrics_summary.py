from __future__ import annotations

from nextorca.session_store import SQLiteSessionStore


def test_metrics_summary_aggregates_usage_latency_and_routes(tmp_path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    workspace = str(tmp_path)
    session_a = store.create_session(workspace=workspace, model="hybrid")
    session_b = store.create_session(workspace=workspace, model="hybrid")
    store.append_event(
        session_a,
        "model_metrics",
        {
            "status": "success",
            "provider": "local",
            "latency_ms": 100.0,
            "input_tokens": 20,
            "output_tokens": 8,
            "task": "explore",
            "route": {"provider": "local", "task": "explore"},
        },
    )
    store.append_event(
        session_a,
        "model_metrics",
        {
            "status": "success",
            "provider": "cloud",
            "latency_ms": 300.0,
            "input_tokens": 40,
            "output_tokens": 12,
            "task": "edit",
            "route": {"provider": "cloud", "task": "edit", "fallback_from": "local"},
        },
    )
    store.append_event(
        session_b,
        "model_metrics",
        {
            "status": "error",
            "provider": "cloud",
            "latency_ms": 50.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "task": "debug",
            "route": {"provider": "cloud", "task": "debug"},
        },
    )

    summary = store.metrics_summary(workspace=workspace)
    assert summary["request_count"] == 3
    assert summary["success_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["input_tokens"] == 60
    assert summary["output_tokens"] == 20
    assert summary["average_latency_ms"] == 150.0
    assert summary["fallback_count"] == 1
    assert summary["sessions"] == 2
    assert summary["by_provider"]["local"]["requests"] == 1
    assert summary["by_task"] == {"explore": 1, "edit": 1, "debug": 1}

    filtered = store.metrics_summary(session_id=session_a)
    assert filtered["request_count"] == 2
    assert filtered["sessions"] == 1
