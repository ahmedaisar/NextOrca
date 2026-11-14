from __future__ import annotations

import os
from pathlib import Path

import pytest

from evals.benchmark import _run_verification, load_manifest

MANIFEST = Path(__file__).parents[1] / "evals" / "benchmark_tasks.json"


@pytest.mark.skipif(os.environ.get("NEXTORCA_FULL_BENCHMARK_TESTS") != "1", reason="full fixture matrix is opt-in")
def test_each_fixture_has_its_documented_baseline_result():
    _version, tasks = load_manifest(MANIFEST)
    fixture_root = MANIFEST.parent / "fixtures"

    for task in tasks:
        fixture = fixture_root / task.fixture.removeprefix("fixtures/")
        result = _run_verification(task, fixture, timeout=30)
        assert result["timed_out"] is False, task.id
        assert result["exit_code"] == task.expected_baseline_exit_code, task.id
