from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from evals.benchmark import (
    FakeProvider,
    _run_runtime_with_deadline,
    build_task_tools,
    load_manifest,
    run_task,
)
from nextorca.tool_registry import ToolExecutionError

MANIFEST = Path(__file__).parents[1] / "evals" / "benchmark_tasks.json"


@pytest.mark.skipif(os.environ.get("NEXTORCA_FULL_BENCHMARK_TESTS") != "1", reason="full fake-provider matrix is opt-in")
def test_fake_provider_completes_all_six_fixture_tasks_without_network():
    _version, tasks = load_manifest(MANIFEST)
    fixture_root = MANIFEST.parent / "fixtures"
    results = []

    for task in tasks:
        results.append(
            run_task(
                task,
                fixture_root=fixture_root,
                provider_factory=lambda selected: (
                    FakeProvider(selected.id),
                    "deterministic-fake",
                    "fake",
                    "fake",
                ),
                source_commit="test-commit",
            )
        )

    assert [result["status"] for result in results] == ["success"] * 6
    assert results[4]["changed_files"] == []
    assert results[4]["read_only_violation"] is False
    assert all(result["input_tokens"] is None for result in results)




def test_fake_provider_smoke_completes_one_task_without_network():
    _version, tasks = load_manifest(MANIFEST)
    task = next(item for item in tasks if item.id == "bug-fix")
    result = run_task(
        task,
        fixture_root=MANIFEST.parent / "fixtures",
        provider_factory=lambda selected: (
            FakeProvider(selected.id),
            "deterministic-fake",
            "fake",
            "fake",
        ),
        source_commit="test-commit",
    )
    assert result["status"] == "success"
    assert result["verification"]["exit_code"] == 0


def test_read_only_task_does_not_expose_write_tool(tmp_path):
    registry = build_task_tools(tmp_path, ("read_file", "list_files"))
    assert "write_file" not in registry.names


def test_verification_tool_runs_only_the_task_pytest_contract(tmp_path):
    _version, tasks = load_manifest(MANIFEST)
    task = next(item for item in tasks if item.id == "bug-fix")
    workspace = tmp_path / "workspace"
    shutil.copytree(MANIFEST.parent / "fixtures" / "bug-fix", workspace)
    registry = build_task_tools(
        workspace,
        task.allowed_tools,
        verification_task=task,
    )

    result = registry.execute("run_verification", {})

    assert "Verification exit code: 1." in result
    assert "AssertionError" in result


def test_task_tools_reject_parent_traversal(tmp_path):
    registry = build_task_tools(tmp_path)
    with pytest.raises(ToolExecutionError):
        registry.execute("read_file", {"path": "../../outside.txt"})


def test_task_tools_write_only_within_workspace(tmp_path):
    registry = build_task_tools(tmp_path)
    result = registry.execute("write_file", {"path": "nested/example.txt", "content": "safe"})
    assert result == "Wrote nested/example.txt."
    assert (tmp_path / "nested" / "example.txt").read_text(encoding="utf-8") == "safe"


@pytest.mark.skipif(os.name == "nt", reason="POSIX interval timers enforce in-process deadlines.")
def test_runtime_deadline_interrupts_a_stalled_runtime():
    class SlowRuntime:
        def run(self, _prompt):
            time.sleep(2)
            return "late"

    with pytest.raises(TimeoutError, match="deadline"):
        _run_runtime_with_deadline(SlowRuntime(), "test", time.monotonic() + 0.1)
