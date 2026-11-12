from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from nextorca.tool_registry import ToolExecutionError
from nextorca.workspace import Workspace


def test_read_accepts_file_exactly_at_byte_limit(tmp_path):
    (tmp_path / "exact.txt").write_bytes(b"1234")
    workspace = Workspace(tmp_path, max_read_bytes=4)

    assert workspace.read("exact.txt") == "1234"


def test_read_rejects_file_over_byte_limit(tmp_path):
    (tmp_path / "large.txt").write_bytes(b"12345")
    workspace = Workspace(tmp_path, max_read_bytes=4)

    with pytest.raises(ToolExecutionError, match="configured read-size limit"):
        workspace.read("large.txt")


def test_grep_skips_file_over_per_file_byte_limit(tmp_path):
    (tmp_path / "large.txt").write_bytes(b"needle")
    workspace = Workspace(tmp_path, max_read_bytes=4)

    assert workspace.grep("needle") == "No matches found."


def test_mutation_read_rejects_file_over_write_byte_limit(tmp_path):
    target = tmp_path / "large.txt"
    target.write_bytes(b"12345")
    workspace = Workspace(tmp_path, max_write_bytes=4)

    with pytest.raises(ToolExecutionError, match="configured size limit"):
        workspace._current_text(target)


def test_read_enforces_limit_even_when_metadata_reports_smaller_size(tmp_path, monkeypatch):
    target = tmp_path / "growth.txt"
    target.write_bytes(b"12345")
    workspace = Workspace(tmp_path, max_read_bytes=4)
    original_stat = Path.stat

    def stale_stat(path: Path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == target:
            return SimpleNamespace(st_mode=result.st_mode, st_size=1)
        return result

    monkeypatch.setattr(Path, "stat", stale_stat)
    assert target.stat().st_size == 1

    with pytest.raises(ToolExecutionError, match="configured read-size limit"):
        workspace.read("growth.txt")


def test_read_and_grep_preserve_utf8_replacement_behavior(tmp_path):
    target = tmp_path / "invalid.txt"
    target.write_bytes(b"\xffabc")
    workspace = Workspace(tmp_path, max_read_bytes=4)

    assert workspace.read("invalid.txt") == "�abc"
    assert workspace.grep("abc") == "invalid.txt:1:�abc"


def test_mutation_read_preserves_strict_utf8_validation(tmp_path):
    target = tmp_path / "invalid.txt"
    target.write_bytes(b"\xffabc")
    workspace = Workspace(tmp_path, max_write_bytes=4)

    with pytest.raises(ToolExecutionError, match="Only UTF-8 text files"):
        workspace._current_text(target)
