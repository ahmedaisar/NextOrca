from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import ClassVar


class SandboxError(RuntimeError):
    """A required operating-system sandbox could not be established."""


class LinuxBubblewrapSandbox:
    """Fail-closed Linux process sandbox backed by bubblewrap."""

    SANDBOX_PATH = "/usr/local/bin:/usr/bin:/bin"
    OUTER_ENV: ClassVar[dict[str, str]] = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    SYSTEM_PATHS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")
    MAX_TMP_BYTES = 128 * 1024 * 1024

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        allow_network: bool = False,
        writable_paths: Sequence[str] = (),
        bwrap_path: str | None = None,
    ) -> None:
        if not sys.platform.startswith("linux"):
            raise SandboxError(
                "MCP execution is disabled: OS-level sandboxing is currently supported "
                "only on Linux with bubblewrap. No unsandboxed fallback is permitted."
            )
        try:
            self.workspace_root = Path(workspace_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SandboxError("Sandbox workspace is unavailable.") from exc
        if not self.workspace_root.is_dir():
            raise SandboxError("Sandbox workspace must be a directory.")
        if not isinstance(allow_network, bool):
            raise SandboxError("network_access must be a boolean.")
        self.allow_network = allow_network
        self.bwrap_path = bwrap_path or shutil.which("bwrap")
        if not self.bwrap_path:
            raise SandboxError(
                "MCP execution requires bubblewrap (bwrap) on Linux. Install bubblewrap "
                "and retry; NextOrca will not launch MCP servers without the sandbox."
            )
        executable = Path(self.bwrap_path)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise SandboxError("Configured bubblewrap executable is not executable.")
        self.bwrap_path = str(executable.resolve(strict=True))
        self.writable_paths = self._resolve_writable_paths(writable_paths)

    def _resolve_writable_paths(self, values: Sequence[str]) -> tuple[tuple[str, Path], ...]:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise SandboxError("writable_paths must be an array of relative directories.")
        mounts: list[tuple[str, Path]] = []
        seen: list[Path] = []
        for value in values:
            if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
                raise SandboxError("Writable workspace paths must be non-empty POSIX paths.")
            relative = PurePosixPath(value)
            if relative.is_absolute() or PureWindowsPath(value).is_absolute():
                raise SandboxError("Writable workspace paths must be relative.")
            raw_parts = value.split("/")
            if (
                not relative.parts
                or any(part in {"", ".", ".."} for part in raw_parts)
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise SandboxError(
                    "Writable workspace paths cannot target the workspace root or contain traversal components."
                )
            candidate = self.workspace_root.joinpath(*relative.parts)
            try:
                resolved = candidate.resolve(strict=True)
                if candidate.absolute() != resolved:
                    raise SandboxError("Writable paths cannot traverse symlinks.")
                resolved.relative_to(self.workspace_root)
            except (OSError, RuntimeError, ValueError) as exc:
                raise SandboxError(
                    f"Writable path {value!r} must be an existing directory inside the workspace."
                ) from exc
            if not resolved.is_dir():
                raise SandboxError(f"Writable path {value!r} is not a directory.")
            if any(
                resolved == item or resolved in item.parents or item in resolved.parents
                for item in seen
            ):
                raise SandboxError("Writable paths must not overlap or contain one another.")
            seen.append(resolved)
            mounts.append((relative.as_posix(), resolved))
        return tuple(mounts)

    def _resolve_command(self, command: Sequence[str], working_directory: Path) -> tuple[str, ...]:
        if (
            not command
            or not all(
                isinstance(item, str) and item and "\x00" not in item
                for item in command
            )
        ):
            raise SandboxError("MCP command must be a non-empty argv array.")
        executable = Path(command[0]).expanduser()
        if not executable.is_absolute() and ("/" in command[0] or "\\" in command[0]):
            executable = working_directory / executable
        elif not executable.is_absolute():
            found = shutil.which(command[0], path=self.SANDBOX_PATH)
            if found is None:
                raise SandboxError(
                    f"MCP executable {command[0]!r} is not available in the sandbox PATH "
                    "(/usr/local/bin, /usr/bin, /bin)."
                )
            executable = Path(found)
        try:
            resolved = executable.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SandboxError("MCP executable could not be resolved.") from exc
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise SandboxError("MCP command does not resolve to an executable file.")
        if self.workspace_root == resolved or self.workspace_root in resolved.parents:
            relative = resolved.relative_to(self.workspace_root)
            sandbox_executable = "/workspace/" + relative.as_posix()
        else:
            system_roots = [Path(value).resolve(strict=False) for value in self.SYSTEM_PATHS]
            if not any(
                resolved == root or root in resolved.parents for root in system_roots
            ):
                raise SandboxError(
                    "MCP executable is outside the sandbox visible system paths and workspace."
                )
            sandbox_executable = str(resolved)
        return (sandbox_executable, *command[1:])

    @staticmethod
    def _add_system_mounts(argv: list[str]) -> None:
        # Mount /usr first; merged-/usr symlinks commonly point into this tree.
        for value in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
            path = Path(value)
            if not path.exists() and not path.is_symlink():
                continue
            if path.is_symlink():
                target = os.readlink(path)
                if os.path.isabs(target):
                    target = os.path.relpath(target, "/")
                argv.extend(["--symlink", target, value])
            else:
                argv.extend(["--ro-bind", value, value])
        argv.extend(
            [
                "--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache",
                "--ro-bind-try", "/etc/nsswitch.conf", "/etc/nsswitch.conf",
                "--ro-bind-try", "/etc/passwd", "/etc/passwd",
                "--ro-bind-try", "/etc/group", "/etc/group",
            ]
        )

    def wrap(
        self,
        command: Sequence[str],
        *,
        working_directory: Path | str,
        environment: Mapping[str, str],
    ) -> tuple[list[str], dict[str, str]]:
        """Return bubblewrap argv and a scrubbed outer environment for Popen."""
        try:
            cwd = Path(working_directory).expanduser().resolve(strict=True)
            relative_cwd = cwd.relative_to(self.workspace_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SandboxError("MCP working directory escapes the configured workspace.") from exc
        if not cwd.is_dir():
            raise SandboxError("MCP working directory must be a directory.")

        resolved_command = self._resolve_command(command, cwd)
        sandbox_cwd = "/workspace"
        if relative_cwd.parts:
            sandbox_cwd += "/" + relative_cwd.as_posix()

        argv = [
            self.bwrap_path,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--cap-drop", "ALL",
            "--size", str(self.MAX_TMP_BYTES),
            "--tmpfs", "/tmp",
            "--proc", "/proc",
            "--dev", "/dev",
            "--dir", "/tmp/nextorca-home",
            "--dir", "/workspace",
        ]
        if self.allow_network:
            argv.append("--share-net")
        self._add_system_mounts(argv)
        argv.extend(["--ro-bind", str(self.workspace_root), "/workspace"])
        for relative, host_path in self.writable_paths:
            argv.extend(["--bind", str(host_path), f"/workspace/{relative}"])
        if self.allow_network:
            argv.extend(
                [
                    "--ro-bind-try", "/etc/ssl/certs", "/etc/ssl/certs",
                    "--ro-bind-try", "/etc/hosts", "/etc/hosts",
                    "--ro-bind-try", "/etc/resolv.conf", "/etc/resolv.conf",
                ]
            )

        safe_environment = {
            "PATH": self.SANDBOX_PATH,
            "HOME": "/tmp/nextorca-home",
            "TMPDIR": "/tmp",
            "TMP": "/tmp",
            "TEMP": "/tmp",
            "LANG": "C.UTF-8",
            "USER": "nextorca",
            "LOGNAME": "nextorca",
            "NEXTORCA_WORKSPACE_ROOT": "/workspace",
        }
        for key, value in environment.items():
            if (
                not isinstance(key, str)
                or not key.replace("_", "a").isalnum()
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise SandboxError("MCP environment contains an invalid variable.")
            if key in safe_environment and value != safe_environment[key]:
                raise SandboxError(f"MCP environment cannot override reserved variable {key!r}.")
            if key.startswith(("LD_", "DYLD_")) or key in {
                "PYTHONPATH", "PYTHONHOME", "BASH_ENV", "ENV"
            }:
                raise SandboxError(f"MCP environment variable {key!r} is not permitted.")
            safe_environment[key] = value

        argv.append("--clearenv")
        for key, value in sorted(safe_environment.items()):
            argv.extend(["--setenv", key, value])
        argv.extend(["--chdir", sandbox_cwd, "--", *resolved_command])
        return argv, dict(self.OUTER_ENV)
