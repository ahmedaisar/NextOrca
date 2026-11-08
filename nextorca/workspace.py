from __future__ import annotations

import fnmatch
from pathlib import Path, PureWindowsPath
from typing import Any

from nextorca.tool_registry import ToolRegistry, ToolSpec, ToolExecutionError


class WorkspaceError(ValueError):
    """A path or operation is outside the configured workspace."""


class Workspace:
    """Read-only filesystem view rooted at one canonical repository directory."""

    def __init__(
        self,
        root: Path | str,
        *,
        max_read_bytes: int = 512_000,
        max_read_chars: int = 24_000,
        max_search_files: int = 500,
        max_search_results: int = 100,
    ) -> None:
        try:
            self.root = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceError("Workspace root is unavailable.") from exc
        if not self.root.is_dir():
            raise WorkspaceError("Workspace root must be a directory.")
        self.max_read_bytes = max_read_bytes
        self.max_read_chars = max_read_chars
        self.max_search_files = max_search_files
        self.max_search_results = max_search_results

    @staticmethod
    def _has_parent_component(value: str) -> bool:
        return ".." in value.replace("\\", "/").split("/")

    def resolve(self, value: str | None, *, allow_root: bool = True) -> Path:
        if value is None or not value or "\x00" in value:
            raise WorkspaceError("A non-empty workspace path is required.")
        if self._has_parent_component(value):
            raise WorkspaceError("Parent-directory traversal is not allowed.")
        supplied = Path(value).expanduser()
        if PureWindowsPath(value).is_absolute() and not supplied.is_absolute():
            raise WorkspaceError("Path must be within the configured workspace.")
        candidate = supplied if supplied.is_absolute() else self.root / supplied
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise WorkspaceError("Path could not be resolved safely.") from exc
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("Path escapes the configured workspace.") from exc
        if not allow_root and resolved == self.root:
            raise WorkspaceError("Path must identify a file within the workspace.")
        return resolved

    def read(self, file_path: str, offset: int = 0, limit: int | None = None) -> str:
        path = self.resolve(file_path, allow_root=False)
        if not path.is_file():
            raise ToolExecutionError("Read target is not a file.")
        try:
            if path.stat().st_size > self.max_read_bytes:
                raise ToolExecutionError("File exceeds the configured read-size limit.")
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise ToolExecutionError("File could not be read.") from exc
        if offset < 0 or (limit is not None and limit < 0):
            raise ToolExecutionError("Read offset and limit must be zero or greater.")
        selected = lines[offset : offset + limit if limit is not None else None]
        text = "\n".join(selected)
        if len(text) > self.max_read_chars:
            text = text[: self.max_read_chars] + "\n[output truncated]"
        return text

    def glob(self, pattern: str, path: str | None = None) -> str:
        self._validate_pattern(pattern)
        base = self.resolve(path or str(self.root))
        if not base.is_dir():
            raise ToolExecutionError("Glob search root is not a directory.")
        matches: list[str] = []
        try:
            candidates = base.glob(pattern)
            for candidate in candidates:
                try:
                    resolved = candidate.resolve(strict=False)
                    resolved.relative_to(self.root)
                except (OSError, RuntimeError, ValueError):
                    continue
                matches.append(str(resolved.relative_to(self.root)))
                if len(matches) >= self.max_search_results:
                    break
        except (OSError, ValueError) as exc:
            raise ToolExecutionError("Glob search failed.") from exc
        return "\n".join(sorted(set(matches))) or "No matches found."

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        output_mode: str = "content",
    ) -> str:
        if not pattern or len(pattern) > 2_000:
            raise ToolExecutionError("Grep pattern must be between 1 and 2000 characters.")
        if output_mode not in {"content", "files", "count"}:
            raise ToolExecutionError("Unsupported grep output mode.")
        if glob:
            self._validate_pattern(glob)
        base = self.resolve(path or str(self.root))
        if not base.is_dir():
            raise ToolExecutionError("Grep search root is not a directory.")

        scanned = 0
        hits = 0
        hit_lines: list[str] = []
        matched_files: set[str] = set()
        for candidate in base.rglob("*"):
            if scanned >= self.max_search_files or hits >= self.max_search_results:
                break
            try:
                resolved = candidate.resolve(strict=False)
                resolved.relative_to(self.root)
            except (OSError, RuntimeError, ValueError):
                continue
            if not resolved.is_file():
                continue
            relative = str(resolved.relative_to(self.root))
            if glob and not fnmatch.fnmatch(relative, glob):
                continue
            scanned += 1
            try:
                if resolved.stat().st_size > self.max_read_bytes:
                    continue
                lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if pattern in line:
                    hits += 1
                    matched_files.add(relative)
                    if output_mode == "content":
                        hit_lines.append(f"{relative}:{line_number}:{line[:500]}")
                    if hits >= self.max_search_results:
                        break

        if output_mode == "count":
            return str(hits)
        if output_mode == "files":
            return "\n".join(sorted(matched_files)) or "No matches found."
        if hits >= self.max_search_results:
            hit_lines.append("[result limit reached]")
        elif scanned >= self.max_search_files:
            hit_lines.append("[file scan limit reached]")
        return "\n".join(hit_lines) or "No matches found."

    @staticmethod
    def _validate_pattern(pattern: str) -> None:
        if not pattern or "\x00" in pattern:
            raise ToolExecutionError("A non-empty glob pattern is required.")
        if Path(pattern).is_absolute() or PureWindowsPath(pattern).is_absolute():
            raise ToolExecutionError("Glob patterns must be relative to the workspace.")
        if Workspace._has_parent_component(pattern):
            raise ToolExecutionError("Glob patterns cannot traverse outside the workspace.")


def build_workspace_tools(workspace: Workspace) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="Read",
            description="Read a UTF-8 text file inside the current workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 0},
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
            handler=lambda args: workspace.read(
                args["file_path"], args.get("offset", 0), args.get("limit")
            ),
        )
    )
    registry.register(
        ToolSpec(
            name="Glob",
            description="List workspace paths matching a relative glob pattern.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "path": {"type": "string", "maxLength": 4096},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            handler=lambda args: workspace.glob(args["pattern"], args.get("path")),
        )
    )
    registry.register(
        ToolSpec(
            name="Grep",
            description="Find literal text inside workspace text files.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "path": {"type": "string", "maxLength": 4096},
                    "glob": {"type": "string", "maxLength": 1024},
                    "output_mode": {
                        "type": "string",
                        "enum": ["content", "files", "count"],
                    },
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
            handler=lambda args: workspace.grep(
                args["pattern"],
                args.get("path"),
                args.get("glob"),
                args.get("output_mode", "content"),
            ),
        )
    )
    return registry
