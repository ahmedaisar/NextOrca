# Plan 002: Enforce workspace byte limits during file reads

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. Keep this implementation in its own PR. Do not broaden it into a general filesystem rewrite.

> **Drift check (run first)**: `git diff --stat f207d19..HEAD -- nextorca/workspace.py tests/test_workspace_limits.py`. If either in-scope file changed since this plan was written, compare the current implementation to the excerpts below before proceeding.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `f207d19`, 2026-11-12

## Why this matters

Workspace operations have configured byte limits, but several paths perform a metadata check and then read the entire file without a read limit. A file can grow between `stat()` and `read_text()`; in that case the metadata check does not bound memory or I/O. Enforce the configured limit on the bytes actually read, not only on the earlier file-size observation. Preserve the current user-facing error behavior and keep Grep's behavior of skipping files that exceed its per-file limit.

## Current state

- `nextorca/workspace.py:71-87` implements `Workspace.read`. It checks `path.stat().st_size` at lines 76–77, then calls unbounded `path.read_text(...)` at line 78.
- `nextorca/workspace.py:142-149` implements the per-file portion of `Workspace.grep`. It checks size at lines 146–147, then calls unbounded `resolved.read_text(...)` at line 148.
- `nextorca/workspace.py:181-193` implements `Workspace._current_text`. It checks size at lines 187–188, then calls unbounded `path.read_text(...)` at line 189.
- `Workspace` defaults `max_read_bytes` and `max_write_bytes` to 512,000 bytes. These limits are part of the existing API and must remain configurable.
- Existing workspace mutation tests use `tmp_path`, construct `Workspace(tmp_path)`, and assert failures with `pytest.raises`; see `tests/test_workspace_mutations.py:158-175` for the prepare/execute mutation-race pattern.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Focused tests | `uv run pytest tests/test_workspace_limits.py tests/test_workspace_mutations.py -q` | All focused tests pass |
| Full tests | `uv run pytest` | Exit 0 |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |

## Scope

**In scope**
- `nextorca/workspace.py`
- `tests/test_workspace_limits.py` (new)

**Out of scope**
- `nextorca/sandbox.py`, `nextorca/mcp_stdio.py`, and `nextorca/session_store.py`.
- Workspace path resolution, symlink policy, checkpoint format, or atomic-write semantics.
- Changing default byte limits, user-visible tool schemas, or the returned text truncation limit.

## Git workflow

- Branch: `fix/bounded-workspace-reads`
- Keep the runtime change and its regression tests in one focused PR.
- Match the existing Ruff/Python style and keep helper functions private unless an existing public API requires otherwise.

## Steps

### Step 1: Introduce a bounded byte-reading primitive

Add a private helper in `nextorca/workspace.py` that opens a file once in binary mode and reads at most `limit + 1` bytes. The extra byte distinguishes a file that fits from one that exceeds the cap. Do not rely on `stat()` as the enforcement mechanism. Handle I/O errors using the existing `ToolExecutionError` conventions at the callers.

**Verify**: `uv run pytest tests/test_workspace_limits.py -q` → helper-level boundary tests pass for exactly-at-limit and one-byte-over-limit inputs.

### Step 2: Apply the primitive consistently

- `Workspace.read`: read no more than `max_read_bytes + 1`; reject an over-limit file with the existing “File exceeds the configured read-size limit.” error; decode UTF-8 using the current replacement behavior; preserve offset, limit, and character truncation semantics.
- `Workspace.grep`: read no more than `max_read_bytes + 1`; skip over-limit files as it currently does; preserve output modes, result limits, and replacement decoding.
- `Workspace._current_text`: read no more than `max_write_bytes + 1`; reject an over-limit file with the existing “Mutation target exceeds the configured size limit.” error; preserve strict UTF-8 decoding.

Remove redundant metadata checks if they no longer add value. Do not read bytes without a hard limit and then check the length afterwards.

**Verify**: `uv run pytest tests/test_workspace_limits.py tests/test_workspace_mutations.py -q` → all limit, UTF-8, read, grep, edit, and checkpoint tests pass.

### Step 3: Add regression tests for stale metadata

Create `tests/test_workspace_limits.py`. Cover:
- `Read` accepts a file exactly at the configured byte limit and rejects one byte over.
- `Grep` skips a file over the configured per-file limit without returning its matching contents.
- `_current_text` rejects an over-limit mutation target.
- A deterministic stale-size test where the earlier metadata observation reports a smaller size than the bytes available to read; the bounded reader must still reject the file without consuming more than the configured limit plus one byte.
- UTF-8 replacement behavior for Read/Grep and strict invalid-UTF-8 rejection for mutation preparation remain unchanged.

Use the public `Workspace` methods where practical. If a test needs a deterministic stale-size simulation, patch only the target path's metadata observation and assert the bounded read itself still enforces the cap.

**Verify**: `uv run pytest tests/test_workspace_limits.py -q` → all new regressions pass.

## Test plan

- Boundary tests at limit and limit + 1 for Read and mutation preparation.
- Grep skip behavior for an oversized file.
- Stale metadata / concurrent-growth simulation proving the enforced bound is based on bytes read.
- Existing edit, write, undo, and approval tests in `tests/test_workspace_mutations.py` remain green.

## Done criteria

- [ ] No workspace file-content path uses `stat().st_size` as the only guard before an unbounded `read_text()`.
- [ ] The actual bytes read by each affected path are capped at the configured limit plus one byte.
- [ ] Existing error messages and UTF-8 behavior are preserved.
- [ ] `uv run pytest` exits 0.
- [ ] `uv run ruff check nextorca tests evals examples` exits 0.
- [ ] No files outside the scope list are modified.

## STOP conditions

Stop and report if:
- Preserving current Read/Grep behavior requires reading the whole file before enforcing the limit.
- A platform-specific file API is required but would remove Windows support.
- The stale-size test cannot be made deterministic without introducing a flaky timing-based race.
- The change requires altering path confinement, symlink policy, or checkpoint semantics.

## Maintenance notes

Keep the byte limit at the I/O boundary. Future workspace tools that read whole files should use the same bounded primitive rather than adding another `stat()`-then-`read_text()` sequence. This plan does not attempt to eliminate every filesystem path race; it specifically closes the gap between metadata size checks and unbounded content reads.
