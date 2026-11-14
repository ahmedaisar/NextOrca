# NextOrca Product Roadmap

**Project:** NextOrca  
**Baseline:** main @ 8d1c38f160f45bc070fd15c0284ab2be0e3ae7a9  
**Updated:** 2026-11-12  
**Scope:** a personal terminal coding agent for the maintainer's own projects. Commercial-readiness requirements are intentionally out of scope.

## Product definition

NextOrca is an AI coding agent that lives in the terminal. It should inspect a repository, edit files with review, run tests and project commands, iterate on failures, use Agent Skills and local plugins, and keep work resumable. Local/cloud orchestration is a behind-the-scenes model selection capability; it must not split the product into separate experiences.

## Shipped foundation

- Full-screen terminal workspace with selectable line-oriented REPL fallback, persistent sessions and slash commands.
- Workspace Read/Glob/Grep, diff-approved Write/Edit and approved shell execution.
- SQLite session history, checkpoints, metrics, resumable session IDs, and explicitly curated project memory with source provenance.
- Standard Agent Skills discovery and on-demand loading.
- Declarative local plugins bundling skills and approval-gated argv command tools.
- MCP stdio integrations with per-call approval and Linux Bubblewrap isolation.
- Goal mode with a worker completion signal, optional verification command and fresh read-only reviewer.
- OpenAI Chat Completions-compatible streaming for text and tool calls.
- Append-only context summaries and recent-turn reconstruction.
- Per-turn local/cloud routing, route/privacy controls and strict local-only behavior.

## Delivery phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Native terminal agent, shell, approved edits, sessions | Complete |
| 2 | Agent Skills discovery and activation | Complete |
| 3 | Declarative plugins and plugin tools | Complete |
| 4 | MCP terminal UX and goal verification/review | Complete |
| 5 | Provider streaming and context compaction | Complete |
| 6 | Seamless local/cloud orchestration | Complete |
| 7 | Product docs, examples, cleanup and end-to-end validation | Complete |
| 8 | Full-screen terminal UI with REPL fallback and session navigation | Complete |
| 9 | Bounded, locally stored project memory with explicit operator controls | Complete with this PR |

## Remaining personal-project backlog

These are optional improvements, not commercial launch gates:

1. Native provider adapters beyond OpenAI Chat Completions compatibility (Plan 007: Anthropic PR #43 in progress; Claude Code CLI, Codex CLI and Gemini API queued as separate PRs).
2. More ergonomic skill/plugin management commands and an optional community catalog.
3. Optional bounded subagents for independent parallel work.
4. Better cancellation and process-tree cleanup for long-running shell commands.
5. More platform coverage for MCP isolation; keep fail-closed behavior where no sandbox exists.
6. Repeatable real-repository task benchmarks for comparing local/cloud routing and models.

## Safety defaults

- File edits show a diff and require approval.
- Shell and plugin commands show the exact command/argv and require approval; they run with the user's OS permissions.
- MCP calls require approval and the configured Linux sandbox; no unsandboxed fallback.
- Skills and plugin manifests are project/user content, not a permission mechanism.
- Local-only mode must never select or fall back to a cloud provider.
- A goal is not accepted until the configured verification succeeds and the independent reviewer explicitly approves. A reviewer is a second model pass, not a formal proof.

## Definition of done

A typical user can start NextOrca in a project, ask it to fix a bug, watch it inspect and edit files, approve the relevant test command, see the actual test result, and continue the same session. They can add a standard skill or a local plugin and optionally route turns between local and cloud models without changing the agent workflow.
