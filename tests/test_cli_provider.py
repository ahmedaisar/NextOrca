from __future__ import annotations

import sys

import pytest

from nextorca.cli_provider import build_cli_prompt, parse_structured_turn, run_cli_process
from nextorca.provider import ProviderError, ProviderUnavailableError


def _tools():
    return [{"type": "function", "function": {"name": "Read", "parameters": {"type": "object"}}}]


def test_build_cli_prompt_separates_system_messages_from_conversation():
    prompt = build_cli_prompt(
        [
            {"role": "system", "content": "Follow project policy"},
            {"role": "user", "content": "Read README"},
        ],
        _tools(),
    )

    assert '"system":"Follow project policy"' in prompt
    assert '"role":"user"' in prompt
    assert '"name":"Read"' in prompt
    assert "NextOrca, not this process" in prompt


def test_parse_structured_turn_validates_tool_names_and_arguments():
    result = parse_structured_turn(
        {
            "content": "Reading the file.",
            "tool_calls": [{"name": "Read", "arguments": {"file_path": "README.md"}}],
        },
        _tools(),
        usage={"input_tokens": 17, "output_tokens": 8},
    )

    assert result.content == "Reading the file."
    assert result.tool_calls[0].name == "Read"
    assert result.tool_calls[0].arguments == {"file_path": "README.md"}
    assert result.tool_calls[0].id.startswith("call_")
    assert result.usage == {"input_tokens": 17, "output_tokens": 8}


def test_parse_structured_turn_rejects_unknown_tools():
    with pytest.raises(ProviderError, match="did not provide"):
        parse_structured_turn(
            {"content": "", "tool_calls": [{"name": "Shell", "arguments": {}}]},
            _tools(),
        )


def test_parse_structured_turn_rejects_non_object_arguments():
    with pytest.raises(ProviderError, match="must be an object"):
        parse_structured_turn(
            {"content": "", "tool_calls": [{"name": "Read", "arguments": "bad"}]},
            _tools(),
        )


def test_run_cli_process_reports_missing_executable(tmp_path):
    with pytest.raises(ProviderError, match="was not found"):
        run_cli_process(
            [str(tmp_path / "missing-cli")],
            "prompt",
            cwd=tmp_path,
            timeout_seconds=1,
        )


def test_run_cli_process_terminates_timed_out_process(tmp_path):
    script = tmp_path / "slow_cli.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")

    with pytest.raises(ProviderUnavailableError, match="timed out"):
        run_cli_process(
            [sys.executable, str(script)],
            "prompt",
            cwd=tmp_path,
            timeout_seconds=0.05,
        )
