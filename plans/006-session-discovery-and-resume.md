# Plan 006: Make persisted sessions discoverable and resumable

> **Executor instructions**: Implement a small session-management layer around the SQLite store. Preserve workspace isolation and the existing append-only transcript model. Do not introduce cross-session memory as part of this plan. Run each verification command before continuing, and update `plans/README.md` when done.

> **Drift check (run first)**: `git diff --stat 7ca0952..HEAD -- nextorca/session_store.py nextorca/cli.py nextorca/repl.py tests/test_session_store.py`. On any change, compare the current SQL/API against the excerpts below and revise or stop before editing.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `7ca0952`, 2026-11-12

## Why this matters

NextOrca stores conversation history in SQLite and supports resume by explicit `--session-id`, but it does not provide a discoverable list or search command for that history. This makes a useful persistent-session feature harder to use because the operator has to save an ID outside the application. A small workspace-scoped list/search interface unlocks one-command resume and provides the stable service that a future TUI can consume.

## Current state

- `nextorca/session_store.py` creates `sessions(session_id, workspace, model, created_at, updated_at)`, `messages(session_id, sequence, message_json, created_at)`, `events` and `checkpoints`.
- `SQLiteSessionStore.create_session()` creates IDs and metadata; `get_session()` returns one record; `ensure_session()` rejects a resume when the stored workspace differs from the requested workspace.
- `SQLiteSessionStore.load_messages()` loads a full transcript in sequence order. There is no `list_sessions` or message-search method in the current module.
- `nextorca/cli.py` exposes `--session-id` and `--session-stats`, but no session list/show/search subcommand. Current parser is a single positional prompt plus options.
- `nextorca/repl.py` supports `/session`, `/new`, `/context`, `/compact`, and `/goal`; it does not provide `/sessions`, history search or a picker.
- `tests/test_session_store.py` already uses `tmp_path`, private SQLite stores and explicit workspace assertions. Extend this pattern.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Session-store tests | `uv run pytest tests/test_session_store.py -q` | All session-store tests pass |
| CLI tests | `uv run pytest tests/test_cli_routing_defaults.py tests/test_runtime_sessions.py -q` | Existing CLI/session behavior remains green |
| Full tests | `uv run pytest` | Exit 0 |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |
| CLI help | `uv run nextorca --help` | Documents the new session command/options without removing existing flags |

## Scope

**In scope**
- `nextorca/session_store.py` — workspace-scoped listing and optional bounded message search.
- `nextorca/cli.py` — a non-provider session-management command or equivalent explicit subcommand.
- `nextorca/repl.py` — small `/sessions` / `/resume` commands, if they fit the existing command grammar.
- `tests/test_session_store.py` and focused CLI/REPL tests.
- `README.md` and `docs/ROADMAP.md` for usage.

**Out of scope**
- Memory embeddings, semantic search or reflection.
- Changing session/message/event schema unless a migration is justified and separately tested.
- Exposing transcripts across unrelated workspaces.
- Deleting/rewriting history or changing append-only message semantics.
- TUI/session rail (Plan 005 consumes this service later).
- Remote APIs, desktop or channel access to session history.

## Git workflow

- Branch: `feat/session-discovery`.
- One focused PR; keep SQLite service and its tests in the same change.
- Existing commit style is Conventional Commits, e.g. `feat: ...`.

## Steps

### Step 1: Add a workspace-scoped session listing API

Add a store method that lists session metadata for one canonical workspace, ordered by `updated_at DESC` with a deterministic tie-breaker. Include ID, model, created_at, updated_at, message count and a bounded preview of the latest user prompt (if available). Use a parameterized query and do not load entire transcripts for the list view.

**Verify**: `uv run pytest tests/test_session_store.py -q` → tests cover ordering, count, preview, empty workspace and separation between two workspaces.

### Step 2: Add bounded history search

Provide optional literal search over user-authored message content with explicit workspace scope and a small result cap. Escape SQL LIKE metacharacters or use a parameterized FTS index only if justified; do not interpret raw user text as SQL or wildcard syntax. Search should return session ID, message sequence/time and a bounded matching excerpt. Avoid searching system prompts, tool results or hidden agent metadata by default.

**Verify**: tests cover Unicode, punctuation/LIKE metacharacters, repeated terms, no matches, max result cap and no cross-workspace matches.

### Step 3: Expose CLI commands without provider startup

Add `nextorca sessions list`, `nextorca sessions search <query>` and `nextorca sessions show <id>` (or a consistent equivalent). These commands should open the store and exit without constructing a provider or starting MCP servers. Reuse the configured `--session-db` path and current workspace canonicalisation.

**Verify**: CLI tests assert output/exit codes and use a fake provider factory that fails if session commands accidentally instantiate a model provider.

### Step 4: Add a short REPL resume path

Add `/sessions` to display recent sessions for the current workspace, and `/resume <id-or-index>` to set the active session using the same workspace validation as `ensure_session`. The command should make the resumed session identity explicit before the next user prompt; no fuzzy selection should silently switch sessions.

**Verify**: REPL tests cover list, exact ID resume, ambiguous/unknown selection and workspace mismatch.

## Test plan

- Store listing: newest-first stable ordering and metadata only.
- Workspace isolation: session IDs and transcripts from another workspace are never returned by list or search.
- Search: literal input, Unicode and SQL wildcard characters; capped result sizes.
- CLI: session commands work offline and do not call provider, shell or MCP.
- REPL: explicit resume retains the existing transcript and session ID.
- Existing session resume and context compaction tests continue to pass.

## Done criteria

- [ ] A user can list sessions for the current workspace without a model provider.
- [ ] A user can search user prompts and resume a chosen session in one command path.
- [ ] Cross-workspace session information remains isolated.
- [ ] Session list/search outputs are bounded and do not expose system prompts, secrets or tool output by default.
- [ ] Existing `--session-id` resume and workspace-binding behavior remain compatible.
- [ ] `uv run pytest`, Ruff and compileall pass.
- [ ] README and roadmap show the new session workflow.

## STOP conditions

Stop and report if:
- A correct list/search implementation requires showing full tool outputs or system/developer messages.
- The session schema cannot provide message counts/previews without an unbounded query or full transcript load.
- The canonical workspace path used by the runtime differs from the workspace key used by the CLI.
- A migration would be needed to support the feature; propose a separate migration plan rather than improvising.
- Any API path can reveal sessions from another workspace.

## Maintenance notes

Treat session search as a local convenience surface over existing data, not a memory system. Keep it SQL-parameterized, bounded and workspace-scoped. A future TUI should consume these APIs and must not duplicate SQL in UI components.
