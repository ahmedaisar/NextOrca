# Plan 005: Add a full-screen terminal workspace without removing the REPL

> **Executor instructions**: Execute this as a focused UI project. Preserve the existing REPL as a supported fallback and keep the agent runtime, provider routing, SQLite store, workspace tools and approval policy as the sources of truth. Do not copy Atomic Agent's TUI architecture wholesale. Run each verification command before continuing. Update the plan index when the implementation is complete.

> **Drift check (run first)**: `git diff --stat d80c604..HEAD -- nextorca/cli.py nextorca/repl.py nextorca/runtime.py nextorca/types.py pyproject.toml tests`. This plan is refreshed after Plan 006 (PR #26) added session discovery APIs and REPL/CLI session commands. If any in-scope path changed again after the baseline, compare this plan's current-state notes to the live code and revise or stop before editing.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: none (Plan 006 provides a session service that the UI should consume when available)
- **Category**: direction
- **Planned at**: commit `7ca0952`, 2026-11-12

## Why this matters

The line-oriented REPL is functional but makes it difficult to inspect conversation history, understand long-running tool activity, navigate sessions and review approvals in a single place. Atomic Agent demonstrates the usability value of a full-screen terminal surface, but NextOrca should keep its much simpler runtime and preserve the current terminal interaction as a fallback. This plan creates a UI around existing events and commands; it must not create a second agent loop or weaken the approval path.

## Current state

- `nextorca/cli.py` owns argument parsing, provider selection, workspace/tool assembly, runtime construction and currently imports `run_repl(runtime)` only for interactive sessions.
- `nextorca/repl.py` implements the current UI using `input()` and `print()`. Its help text exposes `/help`, `/session`, `/sessions`, `/resume`, `/new`, `/tools`, `/route`, `/privacy`, `/context`, `/compact`, `/mcp`, `/plugins`, `/goal` and `/exit`.
- `nextorca/runtime.py` owns provider/tool execution, permission checks, context budget, session persistence and event delivery. Keep it UI-independent.
- `nextorca/session_store.py` exposes bounded, workspace-scoped `list_sessions`, `search_sessions` and `get_session_summary` methods. The CLI exposes provider-free `nextorca sessions list|search|show`; consume these stable interfaces rather than issuing SQL from UI views.
- `nextorca/types.py` defines agent event and stream types; use those event contracts rather than adding UI callbacks deep inside tool implementations.
- `nextorca/permissions.py` implements the existing interactive approval policy. Approval must remain a runtime permission decision, not a TUI-only affordance.
- `pyproject.toml` currently has only `httpx` as a runtime dependency; development dependencies are pytest and Ruff. A terminal UI dependency has not been selected.
- `docs/ROADMAP.md` explicitly lists “A full-screen TUI after the REPL is stable and pleasant” as the first optional personal-project backlog item.
- Existing style is stdlib-first, typed Python, pytest and Ruff; see `nextorca/repl.py` and `tests/test_agent_runtime.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install dev environment | `uv sync --extra dev` | Exit 0 |
| Focused UI/runtime tests | `uv run pytest tests -q` | Exit 0; focused tests included |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |
| CLI smoke | `uv run nextorca --help` | Exit 0 and existing CLI options remain listed |

No new third-party TUI framework should be selected without a short architecture decision comparing maintenance footprint, Windows terminal behavior, non-interactive fallback and testability.

## Suggested executor toolkit

- Use the repository's Product Engineering workflow for planning and cross-boundary code changes.
- Review terminal UI options only if needed to support a tested, accessible and cross-platform terminal interface. Do not introduce a web frontend.

## Scope

**In scope**
- `nextorca/cli.py` — interactive UI selection/wiring only.
- `nextorca/repl.py` — preserve as fallback; extract shared command dispatch only if required.
- New `nextorca/tui.py` or a small `nextorca/tui/` package (choose after architecture note).
- New focused UI tests under `tests/`.
- `pyproject.toml` only if a TUI dependency is justified.
- `README.md` and `docs/ROADMAP.md` for accurate user-facing UI documentation/status.

**Out of scope**
- Rewriting `AgentRuntime`, `HybridRouter`, workspace tools, SQLite persistence or MCP protocol.
- Desktop/Tauri app, HTTP server, browser automation, remote chat channels or web UI.
- Autonomous background task scheduler, parallel subagents and memory retrieval.
- Removing the current REPL or changing one-shot mode's read-only default.
- Changing approval semantics to “trust all” for TUI convenience.

## Git workflow

- Branch: `feat/full-screen-terminal-ui`.
- Use one PR dedicated to the terminal interface.
- Match existing conventional commit style, e.g. `feat: add full-screen terminal UI shell`.
- Keep CI light: focused UI/runtime tests, Ruff, compileall and CLI smoke run on the PR; do not add a full browser or Vercel gate.

## Steps

### Step 1: Record the interface architecture decision

Before choosing a dependency, document the proposed input/event/render architecture and compare at least: stdlib/ANSI terminal rendering, a maintained Python TUI framework, and a lightweight prompt-toolkit/rich-style approach. Consider resize, Windows console support, alternate screen restoration, keyboard input, terminal selection/copy, streaming output, screen-reader legibility, tests and dependency burden. Choose the smallest option that meets these needs.

**Verify**: the architecture note names the chosen approach, records rejected options and includes an explicit statement that the runtime remains UI-agnostic; no code is changed in this step.

### Step 2: Build the smallest useful chat surface

Create a focused TUI entry point that renders message history for the current process, current route/privacy mode, workspace, stream deltas and tool lifecycle events. It must recover terminal state after normal exit, Ctrl-C and raised exceptions. Use the existing runtime's `on_event` stream and existing runtime methods; do not add TUI-only execution paths.

**Verify**: focused UI tests prove that assistant deltas, tool start/completion/denial/error events, and final text render in the expected order; terminal restoration tests pass for normal and exceptional exit.

### Step 3: Make approval a first-class, accessible interaction

Adapt the approval prompt to the chosen TUI without changing the permission policy. Show the operation preview, affected path/command, and safe default-deny choices. Ensure approval remains synchronous with the operation and rejects input loss when a model response or tool event is streaming.

**Verify**: tests demonstrate approve-once, decline, EOF/Ctrl-C denial, and that no mutation executes without an explicit affirmative answer.

### Step 4: Add navigation and status surfaces

Add a minimal sidebar/panel or keyboard-accessible views for current session, available tools, route/privacy, context status, MCP/plugins and active goal. Do not build provider management or a complete settings centre as part of this plan. Integrate Plan 006's session API if it has landed; otherwise keep session selection behind a small interface that can adopt it later.

**Verify**: tests cover switching views, narrow terminal dimensions, unknown/unsupported key sequences and no accidental action on resize.

### Step 5: Integrate without breaking the REPL

Add an explicit UI selector (for example `--ui auto|tui|repl`) or a clear fallback policy. Keep non-TTY and one-shot behavior unchanged. If the selected TUI cannot initialise (unsupported terminal, missing optional dependency), fail with an actionable message or fall back only when configured to do so—never silently run commands under a different interaction mode.

**Verify**: `uv run nextorca --help` documents the selector; existing CLI parser tests pass; a non-TTY invocation continues to require a prompt and does not launch a full-screen UI.

## Test plan

- Event rendering order: assistant delta → tool started → tool completed/denied/error → final response.
- Approval cannot bypass `InteractiveApprovalPolicy`; declined and interrupted requests leave the workspace unchanged.
- Terminal alternate-screen/raw-mode restoration on normal exit, exceptions, Ctrl-C and resize.
- Small terminal layouts and UTF-8/Unicode display.
- REPL fallback and one-shot read-only mode remain unchanged.
- Existing `tests/test_agent_runtime.py`, `tests/test_streaming_runtime.py`, `tests/test_hybrid_streaming.py` remain green.

## Done criteria

- [ ] Full-screen terminal UI can run one complete interactive session on a supported terminal.
- [ ] Existing REPL remains selectable and works as before.
- [ ] UI consumes the existing runtime/event and approval contracts; no duplicate agent loop is introduced.
- [ ] All operations that mutate state still require the current explicit approval.
- [ ] Terminal state is restored on every tested exit path.
- [ ] `uv run pytest`, Ruff, compileall and CLI smoke checks pass.
- [ ] README and roadmap accurately document supported terminals and fallback behavior.
- [ ] No desktop/web/channel/browser scope was added.

## STOP conditions

Stop and report if:
- The chosen TUI library cannot support reliable terminal restoration or Windows behavior without replacing core runtime code.
- UI implementation requires direct database access from view components rather than a session/runtime service.
- Streaming and approval input cannot be multiplexed without risking lost user input or unintended approvals.
- A terminal-library dependency materially increases package complexity without a clear accessibility/testability benefit.
- Existing REPL behavior or one-shot read-only policy would need to change.

## Maintenance notes

Keep TUI state separate from agent/session state. UI widgets should render runtime events and call explicit runtime/session APIs; they must not own provider routing, tool execution, session persistence or approval policy. Review input precedence, terminal restoration and Windows behavior carefully. Advanced model-management screens, session search implementation and mouse support belong in separate increments.
