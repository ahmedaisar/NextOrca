from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.benchmark import BenchmarkError, load_manifest

MANIFEST = Path(__file__).parents[1] / "evals" / "benchmark_tasks.json"


def _write_manifest(tmp_path: Path, task_overrides: dict | None = None, **root_overrides) -> Path:
    fixture = tmp_path / "evals" / "fixtures" / "sample"
    fixture.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "corpus_version": "test-1",
        "tasks": [
            {
                "id": "sample-task",
                "category": "bug_fix",
                "description": "A sample fixture task.",
                "fixture": "fixtures/sample",
                "prompt": "Fix the sample fixture.",
                "allowed_tools": ["read_file", "write_file"],
                "verification_argv": ["python", "-m", "pytest", "-q"],
                "timeout_seconds": 10,
                "max_turns": 3,
                "max_tool_calls": 5,
                "expected_baseline_exit_code": 1,
            }
        ],
    }
    payload.update(root_overrides)
    if task_overrides:
        payload["tasks"][0].update(task_overrides)
    path = tmp_path / "evals" / "benchmark_tasks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_repository_manifest_loads_six_unique_tasks():
    version, tasks = load_manifest(MANIFEST)

    assert version == "1.0.0"
    assert len(tasks) == 6
    assert len({task.id for task in tasks}) == 6


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"fixture": "../outside"}, "relative"),
        ({"verification_argv": ["sh", "-c", "echo unsafe"]}, "pytest argv"),
        ({"verification_argv": ["python", "-m", "pytest", "-q", "../../etc/passwd"]}, "safe relative"),
        ({"allowed_tools": ["write_file", "shell"]}, "allowed_tools"),
        ({"timeout_seconds": 901}, "timeout_seconds"),
        ({"max_tool_calls": 0}, "max_tool_calls"),
        ({"read_only": True}, "read_only"),
    ],
)
def test_manifest_rejects_unsafe_or_out_of_bounds_task_fields(tmp_path, overrides, message):
    path = _write_manifest(tmp_path, overrides)

    with pytest.raises(BenchmarkError, match=message):
        load_manifest(path)


def test_manifest_rejects_unknown_schema_version(tmp_path):
    path = _write_manifest(tmp_path, schema_version=2)

    with pytest.raises(BenchmarkError, match="schema version"):
        load_manifest(path)


def test_manifest_rejects_duplicate_task_ids(tmp_path):
    path = _write_manifest(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["tasks"].append(dict(payload["tasks"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BenchmarkError, match="unique"):
        load_manifest(path)
