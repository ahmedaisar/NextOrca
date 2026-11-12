# Plan 008: Design and prototype bounded cross-session project memory

> **Executor instructions**: Treat this as a privacy-sensitive, staged design/prototype plan, not permission to build a large memory platform. First produce a minimal design and acceptance corpus. Store memory locally and make every remembered fact inspectable and deletable. Do not add cloud embeddings or background reflection in the first increment.

> **Drift check (run first)**: `git diff --stat 615233e..HEAD -- nextorca/session_store.py nextorca/context.py nextorca/runtime.py nextorca/cli.py nextorca/repl.py nextorca/tui.py tests README.md docs/project-memory.md docs/ROADMAP.md`. This implementation is stacked on the session/TUI and clean provider-registry branches. Compare the live SQLite schema, context injection and commands before editing; review any later drift before proceeding.

## Status

- **Execution state**: COMPLETE — [PR #30](https://github.com/ahmedaisar/NextOrca/pull/30), latest PR CI passed.
- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/006-session-discovery-and-resume.md
- **Category**: direction
- **Planned at**: commit `615233e`, 2026-11-12

## Why this matters

NextOrca's current compaction keeps a useful summary inside one session, but it does not create a searchable memory that can inform a different session in the same project. Atomic Agent has a separate cross-session memory fabric, including structured profile facts, searchable notes and reflection; importing that level of complexity is unnecessary for a personal coding agent. This plan first defines a bounded, local-only project memory for durable coding decisions and recurring project facts, with transparent provenance and operator control.

## Current state

- `nextorca/context.py` implements a deterministic character-budget fit that prunes older tool and assistant output while preserving required messages; it is not a persistent recall index.
- `nextorca/runtime.py` stores append-only message/event history and compaction summaries. Context compaction is for reconstructing one session's prompt.
- `nextorca/session_store.py` persists sessions, messages, events and checkpoints. Its `sessions` table carries ID, workspace, model and timestamps; message history is associated with session ID. The implementation in this branch adds `project_memories` and `project_memory_settings` tables to the same owner-only SQLite database, with a hard 2,000-record workspace cap.
- `nextorca/runtime.py` now uses the lexical search API to inject at most four matched records into an ephemeral system-context block. It applies the normal context budget and drops optional memory if it would make an otherwise valid prompt fail.
- `nextorca/cli.py` and `nextorca/repl.py` expose `memory add/list/show/search/forget/on/off/status`; the TUI routes `/memory` commands through the same REPL command helper.
- `docs/project-memory.md` documents explicit creation, provenance, credential rejection, local storage and the fact that selected memory enters the current provider prompt. Balanced mode can route prompts to cloud; local-only mode preserves the local-inference boundary.
- Existing tests use temporary SQLite files and explicit workspace binding. Preserve the principle that one project's memory must not leak into another project's sessions.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Session/memory tests | `uv run pytest tests/test_session_store.py tests/test_context_compaction.py tests/test_context_budget.py -q` | Existing session/context tests pass |
| Full tests | `uv run pytest` | Exit 0 |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |

## Scope

**In scope**
- `nextorca/session_store.py` — local project memory tables and workspace-scoped CRUD/retrieval methods in the existing 0600 SQLite store.
- `nextorca/runtime.py` — ephemeral, bounded prompt injection with provenance and context-budget fallback.
- `nextorca/cli.py`, `nextorca/repl.py`, and `nextorca/tui.py` — inspect, add, forget, preview and enable/disable commands.
- Focused tests under `tests/test_project_memory_*.py` and `tests/test_cli_project_memory.py` / `tests/test_repl_project_memory.py`.
- `docs/project-memory.md`, `README.md`, and `docs/ROADMAP.md`.

**Out of scope**
- Replacing or rewriting session transcripts.
- Sending memory contents to cloud providers when local-only mode is active or memory is disabled.
- Remote/vector databases, external embedding APIs, background reflection, autonomous extraction or automatic profile inference in the first increment.
- User-wide/person-wide memory shared across unrelated workspaces.
- Automatic writes of credentials, tokens, personal data or arbitrary tool output into memory.
- Any new scheduler, channel or desktop interface.

## Steps

### Step 1: Write the minimal memory contract

Define supported memory records such as project decisions, recurring commands, environment facts and repository conventions. Every record must include source session/message reference, created/updated timestamps, workspace identity, confidence or verification status, and a bounded text payload. Decide whether a memory item is explicitly user-authored or agent-proposed pending approval; the first version should prefer explicit operator confirmation for persisted writes.

**Verify**: documentation and schema tests define each field, allowable record types, limits, and what is never stored.

### Step 2: Build deterministic local storage and explicit controls

Create a local SQLite-backed store or a separate table with prepared SQL and workspace isolation. Add `memory list`, `memory show`, `memory add`, `memory forget` and `memory off/on` or equivalent. Deletion must be durable and must not silently retain deleted text in a derived index.

**Verify**: tests cover add/list/show/forget, disable/enable, workspace isolation, invalid schema, maximum record size and database file permissions.

### Step 3: Retrieve only bounded, relevant items

Start with simple lexical matching over user-approved memory records. Inject only a small number of matched records into the next session's context, with provenance and an explicit “project memory” label. No automatic reflection or embedding API is introduced in this increment.

**Verify**: tests prove unrelated memory is not injected, results obey a strict character budget, source references are retained, and disabled memory results in zero memory content in provider messages.

### Step 4: Add an evaluation corpus and operator review

Create a small fixture corpus drawn from synthetic project decisions and command conventions. Evaluate retrieval precision, recall, stale-fact handling and deletion. Add a simple command to display which memories were selected for a turn.

**Verify**: deterministic tests show correct project-scoped recall for known queries and no recall for unrelated workspaces, deleted records or disabled memory.

## Test plan

- Workspace isolation across separate repositories.
- Explicit consent/confirmation before a record is written.
- Provenance remains attached to every retrieved record.
- Disabled memory never affects the prompt.
- Forget deletes the source record and any search-derived representation.
- Memory injection stays within a fixed budget and cannot replace system instructions or override safety policy.
- Synthetic retrieval evaluation is repeatable and does not require an external embedding service.

## Done criteria

- [ ] Memory is stored locally, project-scoped, inspectable and deletable.
- [ ] Every item has source provenance and `operator_confirmed` status; creation is explicit, never automatic.
- [ ] Memory can be disabled with a guarantee that no memory content is injected into provider messages.
- [ ] Retrieval is bounded, deterministic and covered by synthetic evaluations; optional memories are dropped if they would exceed the context budget.
- [ ] Existing session transcripts and compaction behavior are unchanged.
- [ ] Full pytest, Ruff and compileall pass.
- [ ] Documentation explains what is stored, why, where and how to forget it.

## STOP conditions

Stop and report if:
- Memory records cannot be reliably separated by canonical workspace.
- A meaningful first version requires external embeddings, a cloud database or background model calls.
- The system proposes storing secrets, personal data or content without a clear operator review path.
- Deleted content remains reachable through a derived index or compaction snapshot without an explicit retention policy.
- The feature adds meaningful provider context without an auditable “why this memory was selected” explanation.

## Maintenance notes

Do not treat session compaction and cross-session memory as the same feature. Compaction preserves continuity inside one transcript; memory is curated project knowledge across transcripts. Keep the memory layer local, scoped, provenance-bearing and easy to disable. Revisit embeddings/reflection only after the deterministic prototype demonstrates measurable retrieval value on real project tasks.
