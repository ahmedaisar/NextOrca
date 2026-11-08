from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from nextorca.sandbox import LinuxBubblewrapSandbox, SandboxError


SYSTEM_TEST_PYTHON = "/usr/bin/python3"


def _fake_bwrap(path: Path) -> Path:
    binary = path / "bwrap"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


def test_sandbox_is_linux_only_and_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr("nextorca.sandbox.sys.platform", "darwin")
    with pytest.raises(SandboxError, match="only on Linux"):
        LinuxBubblewrapSandbox(tmp_path, bwrap_path="/bin/true")


def test_missing_bubblewrap_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr("nextorca.sandbox.shutil.which", lambda _name: None)
    with pytest.raises(SandboxError, match="requires bubblewrap"):
        LinuxBubblewrapSandbox(tmp_path)


def test_default_sandbox_has_no_network_and_workspace_is_read_only(tmp_path):
    sandbox = LinuxBubblewrapSandbox(tmp_path, bwrap_path=str(_fake_bwrap(tmp_path)))
    argv, outer_env = sandbox.wrap(
        [SYSTEM_TEST_PYTHON, "-c", "print('hello')"],
        working_directory=tmp_path,
        environment={},
    )
    assert "--unshare-all" in argv
    assert "--cap-drop" in argv and "ALL" in argv
    assert "--ro-bind" in argv
    assert str(tmp_path.resolve()) in argv
    assert "/workspace" in argv
    assert "--share-net" not in argv
    assert "--bind" not in argv
    assert outer_env == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


def test_network_access_is_explicit_and_mounts_resolver_inputs(tmp_path):
    sandbox = LinuxBubblewrapSandbox(
        tmp_path, allow_network=True, bwrap_path=str(_fake_bwrap(tmp_path))
    )
    argv, _ = sandbox.wrap(
        [SYSTEM_TEST_PYTHON, "-c", "pass"],
        working_directory=tmp_path,
        environment={},
    )
    assert "--share-net" in argv
    assert "/etc/resolv.conf" in argv
    assert "/etc/ssl/certs" in argv


def test_only_existing_confined_directories_can_be_writable(tmp_path):
    writable = tmp_path / "artifacts"
    writable.mkdir()
    sandbox = LinuxBubblewrapSandbox(
        tmp_path,
        writable_paths=("artifacts",),
        bwrap_path=str(_fake_bwrap(tmp_path)),
    )
    argv, _ = sandbox.wrap(
        [SYSTEM_TEST_PYTHON, "-c", "pass"],
        working_directory=tmp_path,
        environment={},
    )
    bind_index = argv.index("--bind")
    assert argv[bind_index + 1] == str(writable.resolve())
    assert argv[bind_index + 2] == "/workspace/artifacts"


@pytest.mark.parametrize("value", ["../outside", "/etc", "C:\\Windows", "a/../b", ""])
def test_writable_path_rejects_traversal_and_absolute_paths(tmp_path, value):
    with pytest.raises(SandboxError):
        LinuxBubblewrapSandbox(
            tmp_path, writable_paths=(value,), bwrap_path=str(_fake_bwrap(tmp_path))
        )


def test_writable_path_rejects_symlink_escape_and_overlapping_mounts(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    link = tmp_path / "escape"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SandboxError):
        LinuxBubblewrapSandbox(
            tmp_path, writable_paths=("escape",), bwrap_path=str(_fake_bwrap(tmp_path))
        )

    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    with pytest.raises(SandboxError, match="must not overlap"):
        LinuxBubblewrapSandbox(
            tmp_path,
            writable_paths=("parent", "parent/child"),
            bwrap_path=str(_fake_bwrap(tmp_path)),
        )


def test_command_and_working_directory_must_be_confined(tmp_path):
    sandbox = LinuxBubblewrapSandbox(tmp_path, bwrap_path=str(_fake_bwrap(tmp_path)))
    outside = tmp_path.parent
    with pytest.raises(SandboxError, match="working directory escapes"):
        sandbox.wrap(
            [SYSTEM_TEST_PYTHON, "-c", "pass"],
            working_directory=outside,
            environment={},
        )
    outside_executable = outside / "external-command"
    outside_executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    outside_executable.chmod(0o755)
    with pytest.raises(SandboxError, match="outside the sandbox"):
        sandbox.wrap(
            [str(outside_executable)],
            working_directory=tmp_path,
            environment={},
        )


def test_reserved_or_dynamic_loader_environment_cannot_be_overridden(tmp_path):
    sandbox = LinuxBubblewrapSandbox(tmp_path, bwrap_path=str(_fake_bwrap(tmp_path)))
    with pytest.raises(SandboxError, match="cannot override reserved"):
        sandbox.wrap(
            [SYSTEM_TEST_PYTHON],
            working_directory=tmp_path,
            environment={"PATH": "/tmp/evil"},
        )
    with pytest.raises(SandboxError, match="not permitted"):
        sandbox.wrap(
            [SYSTEM_TEST_PYTHON],
            working_directory=tmp_path,
            environment={"LD_PRELOAD": "/tmp/evil.so"},
        )


def test_bubblewrap_runtime_enforces_read_only_workspace(tmp_path):
    bwrap = shutil.which("bwrap")
    python = Path(SYSTEM_TEST_PYTHON)
    if not bwrap or not python.is_file():
        pytest.skip("bubblewrap and the system Python runtime are required for this smoke test.")
    sandbox = LinuxBubblewrapSandbox(tmp_path, bwrap_path=bwrap)
    code = """from pathlib import Path
p = Path('/workspace/blocked.txt')
try:
    p.write_text('not allowed')
except OSError:
    print('workspace-read-only')
else:
    raise SystemExit('workspace unexpectedly writable')
Path('/tmp/sandbox-write.txt').write_text('allowed')
"""
    argv, environment = sandbox.wrap(
        [str(python), "-c", code],
        working_directory=tmp_path,
        environment={},
    )
    completed = subprocess.run(
        argv,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "workspace-read-only" in completed.stdout


def test_workspace_executable_is_rewritten_to_sandbox_path(tmp_path):
    script = tmp_path / "bin" / "inspect"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    sandbox = LinuxBubblewrapSandbox(tmp_path, bwrap_path=str(_fake_bwrap(tmp_path)))
    argv, _ = sandbox.wrap(
        [str(script), "--version"],
        working_directory=tmp_path,
        environment={},
    )
    command_index = argv.index("--") + 1
    assert argv[command_index] == "/workspace/bin/inspect"
    assert argv[command_index + 1] == "--version"


@pytest.mark.parametrize("value", [".", "./", "a/./b", "a//b", "artifacts/"])
def test_writable_path_rejects_ambiguous_components_and_workspace_root(tmp_path, value):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    nested = artifacts / "b"
    nested.mkdir(exist_ok=True)
    with pytest.raises(SandboxError):
        LinuxBubblewrapSandbox(
            tmp_path, writable_paths=(value,), bwrap_path=str(_fake_bwrap(tmp_path))
        )


def test_writable_path_rejects_internal_symlink(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(SandboxError, match="cannot traverse symlinks"):
        LinuxBubblewrapSandbox(
            tmp_path, writable_paths=("alias",), bwrap_path=str(_fake_bwrap(tmp_path))
        )
