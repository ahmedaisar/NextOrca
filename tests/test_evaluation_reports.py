from __future__ import annotations

import json

from evals.benchmark import build_summary, write_reports


def test_summary_uses_null_for_missing_usage_and_stable_json(tmp_path):
    results = [
        {
            "task_id": "read-only-explanation",
            "category": "explanation",
            "status": "success",
            "elapsed_ms": 12.5,
            "input_tokens": None,
            "output_tokens": None,
            "verification": {"exit_code": 0, "timed_out": False},
        }
    ]
    summary = build_summary(corpus_version="1.0.0", source_commit="abc123", results=results)

    assert summary["usage"] == {"input_tokens": None, "output_tokens": None}
    assert summary["success_rate"] == 1.0
    first, second = write_reports(summary, tmp_path)
    assert json.loads(first.read_text(encoding="utf-8")) == summary
    assert json.loads(second.read_text(encoding="utf-8")) == results
    assert first.read_text(encoding="utf-8") == json.dumps(
        summary, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"


def test_report_does_not_include_prompts_transcripts_or_environment(tmp_path):
    summary = build_summary(
        corpus_version="1.0.0",
        source_commit="abc123",
        results=[
            {
                "task_id": "sample",
                "category": "bug_fix",
                "status": "failed",
                "elapsed_ms": 5,
                "input_tokens": None,
                "output_tokens": None,
                "verification": {"exit_code": 1, "timed_out": False},
                "runtime_error": "ProviderError",
            }
        ],
    )
    aggregate, runs = write_reports(summary, tmp_path)
    output = aggregate.read_text(encoding="utf-8") + runs.read_text(encoding="utf-8")

    assert "transcript" not in output.lower()
    assert "api_key" not in output.lower()
    assert "prompt" not in output.lower()
