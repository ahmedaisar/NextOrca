from __future__ import annotations

import difflib
import fnmatch
import os
import stat
import tempfile
from pathlib import Path, PureWindowsPath

from nextorca.session_store import SQLiteSessionStore
from nextorca.tool_registry import PreparedToolOperation, ToolExecutionError, ToolRegistry, ToolSpec


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
        max_write_bytes: int = 512_000,
        max_diff_chars: int = 12_000,
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
        self.max_write_bytes = max_write_bytes
        self.max_diff_chars = max_diff_chars
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



    def _current_text(self, path: Path) -> tuple[bool, str]:
        if not path.exists():
            return False, ""
        if not path.is_file():
            raise ToolExecutionError("Mutation target is not a regular file.")
        try:
            if path.stat().st_size > self.max_write_bytes:
                raise ToolExecutionError("Mutation target exceeds the configured size limit.")
            return True, path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolExecutionError("Only UTF-8 text files can be edited.") from exc
        except OSError as exc:
            raise ToolExecutionError("Mutation target could not be read.") from exc

    def _diff(self, path: Path, before: str, after: str, before_exists: bool) -> str:
        relative = str(path.relative_to(self.root))
        before_name = relative if before_exists else "/dev/null"
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=before_name,
                tofile=relative,
            )
        )
        if not diff:
            return "No changes."
        if len(diff) > self.max_diff_chars:
            diff = diff[: self.max_diff_chars] + "\n[diff preview truncated]"
        return diff

    def _atomic_write(self, path: Path, content: str) -> None:
        if len(content.encode("utf-8")) > self.max_write_bytes:
            raise ToolExecutionError("New file content exceeds the configured size limit.")
        temporary_name: str | None = None
        descriptor: int | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            parent = path.parent.resolve(strict=True)
            parent.relative_to(self.root)
            destination = parent / path.name
            if destination.is_symlink():
                destination = destination.resolve(strict=True)
                destination.relative_to(self.root)
            mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else 0o644
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.nextorca-",
                dir=parent,
            )
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, mode)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                descriptor = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
            if hasattr(os, "chmod"):
                os.chmod(destination, mode)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ToolExecutionError("File could not be written safely.") from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    def _apply_change(
        self,
        *,
        path: Path,
        before_exists: bool,
        before_content: str,
        after_content: str,
        checkpoint_store: SQLiteSessionStore,
        operation_name: str,
    ) -> str:
        current_exists, current_content = self._current_text(path)
        if current_exists != before_exists or current_content != before_content:
            raise ToolExecutionError(
                "File changed after approval preview; generate a new diff and approve again."
            )
        if before_exists and before_content == after_content:
            return f"No changes to {path.relative_to(self.root)}; no checkpoint created."

        self._atomic_write(path, after_content)
        try:
            checkpoint_id = checkpoint_store.create_checkpoint(
                workspace=str(self.root),
                path=str(path),
                before_exists=before_exists,
                before_content=before_content,
                after_content=after_content,
            )
        except Exception as exc:
            try:
                if before_exists:
                    self._atomic_write(path, before_content)
                elif path.exists():
                    path.unlink()
            except Exception as rollback_exc:
                raise ToolExecutionError(
                    "Checkpoint creation failed and automatic rollback also failed."
                ) from rollback_exc
            raise ToolExecutionError(
                "Checkpoint creation failed; the file change was rolled back."
            ) from exc

        relative = str(path.relative_to(self.root))
        return (
            f"{operation_name} {relative}. Checkpoint ID: {checkpoint_id}\n"
            f"{self._diff(path, before_content, after_content, before_exists)}"
        )

    def prepare_write(
        self,
        arguments: dict[str, Any],
        checkpoint_store: SQLiteSessionStore,
    ) -> PreparedToolOperation:
        path = self.resolve(arguments["file_path"], allow_root=False)
        content = arguments["content"]
        if len(content.encode("utf-8")) > self.max_write_bytes:
            raise ToolExecutionError("New file content exceeds the configured size limit.")
        before_exists, before_content = self._current_text(path)
        if before_exists and not arguments.get("overwrite", False):
            raise ToolExecutionError(
                "File already exists; set overwrite=true to request an approved replacement."
            )
        preview = self._diff(path, before_content, content, before_exists)
        return PreparedToolOperation(
            preview=preview,
            execute=lambda: self._apply_change(
                path=path,
                before_exists=before_exists,
                before_content=before_content,
                after_content=content,
                checkpoint_store=checkpoint_store,
                operation_name="Wrote",
            ),
        )

    def prepare_edit(
        self,
        arguments: dict[str, Any],
        checkpoint_store: SQLiteSessionStore,
    ) -> PreparedToolOperation:
        path = self.resolve(arguments["file_path"], allow_root=False)
        before_exists, before_content = self._current_text(path)
        if not before_exists:
            raise ToolExecutionError("Edit target does not exist.")
        old_string = arguments["old_string"]
        new_string = arguments["new_string"]
        replace_all = arguments.get("replace_all", False)
        occurrences = before_content.count(old_string)
        if occurrences == 0:
            raise ToolExecutionError("Edit target text was not found.")
        if occurrences > 1 and not replace_all:
            raise ToolExecutionError(
                "Edit target text occurs more than once; set replace_all=true or narrow the match."
            )
        after_content = (
            before_content.replace(old_string, new_string)
            if replace_all
            else before_content.replace(old_string, new_string, 1)
        )
        if len(after_content.encode("utf-8")) > self.max_write_bytes:
            raise ToolExecutionError("Edited file exceeds the configured size limit.")
        preview = self._diff(path, before_content, after_content, True)
        return PreparedToolOperation(
            preview=preview,
            execute=lambda: self._apply_change(
                path=path,
                before_exists=True,
                before_content=before_content,
                after_content=after_content,
                checkpoint_store=checkpoint_store,
                operation_name="Edited",
            ),
        )

    def undo_checkpoint(
        self,
        checkpoint_id: str,
        checkpoint_store: SQLiteSessionStore,
    ) -> str:
        checkpoint = checkpoint_store.get_checkpoint(checkpoint_id)
        if checkpoint is None:
            raise ToolExecutionError("Checkpoint was not found.")
        if checkpoint["workspace"] != str(self.root):
            raise WorkspaceError("Checkpoint belongs to a different workspace.")
        if checkpoint["undone_at"] is not None:
            raise ToolExecutionError("Checkpoint has already been undone.")

        path = self.resolve(checkpoint["path"], allow_root=False)
        exists, current = self._current_text(path)
        if not exists or current != checkpoint["after_content"]:
            raise ToolExecutionError(
                "File has changed since this checkpoint; refusing to overwrite newer work."
            )

        if checkpoint["before_exists"]:
            self._atomic_write(path, checkpoint["before_content"])
        else:
            try:
                path.unlink()
            except OSError as exc:
                raise ToolExecutionError("New file could not be removed during undo.") from exc

        try:
            checkpoint_store.mark_checkpoint_undone(checkpoint_id)
        except Exception as exc:
            try:
                self._atomic_write(path, checkpoint["after_content"])
            except Exception as rollback_exc:
                raise ToolExecutionError(
                    "Undo completed but its state could not be recorded or restored."
                ) from rollback_exc
            raise ToolExecutionError(
                "Undo state could not be recorded; the original change was restored."
            ) from exc

        return f"Undid checkpoint {checkpoint_id} for {path.relative_to(self.root)}."

    def list_checkpoints(
        self,
        checkpoint_store: SQLiteSessionStore,
    ) -> list[dict[str, Any]]:
        return checkpoint_store.list_checkpoints(str(self.root))


def build_workspace_tools(
    workspace: Workspace,
    *,
    include_mutations: bool = False,
    checkpoint_store: SQLiteSessionStore | None = None,
) -> ToolRegistry:
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

    if include_mutations:
        if checkpoint_store is None:
            raise ValueError("A persistent checkpoint store is required for write/edit tools.")
        registry.register(
            ToolSpec(
                name="Write",
                description="Create a UTF-8 text file in the workspace; replacement requires overwrite=true and approval.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "minLength": 1, "maxLength": 4096},
                        "content": {"type": "string", "maxLength": 512000},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["file_path", "content"],
                    "additionalProperties": False,
                },
                handler=lambda _args: "Write must run through the approval pipeline.",
                read_only=False,
                prepare_handler=lambda args: workspace.prepare_write(args, checkpoint_store),
            )
        )
        registry.register(
            ToolSpec(
                name="Edit",
                description="Replace exact text in a workspace file; the resulting diff requires approval.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "minLength": 1, "maxLength": 4096},
                        "old_string": {"type": "string", "minLength": 1, "maxLength": 512000},
                        "new_string": {"type": "string", "maxLength": 512000},
                        "replace_all": {"type": "boolean"},
                    },
                    "required": ["file_path", "old_string", "new_string"],
                    "additionalProperties": False,
                },
                handler=lambda _args: "Edit must run through the approval pipeline.",
                read_only=False,
                prepare_handler=lambda args: workspace.prepare_edit(args, checkpoint_store),
            )
        )
    return registry
