# Atomic Agent feature comparison audit

**Audit date:** 2026-11-12  
**NextOrca baseline:** `main` at `7ca0952235c7e8146fca49aa6e24f484b3bedc9b`  
**Reference:** [AtomicBot-ai/atomic-agent](https://github.com/AtomicBot-ai/atomic-agent), default branch `main`, inspected 2026-11-12  
**Purpose:** feature comparison and prioritised product direction for NextOrca as a personal terminal coding agent.  
**Method:** read-only repository reconnaissance: public READMEs, project roadmaps, package manifests, source trees, selected current implementation modules, feature-specific module guides, and representative tests. No code was changed in either project.

> This is a product and implementation-surface comparison, not a line-by-line security audit, benchmark, or claim that every feature in Atomic Agent works equally well in every environment. Atomic Agent is a much larger codebase (approximately 4,120 tracked tree entries surfaced by GitHub's recursive tree endpoint, compared with 67 for NextOrca at this snapshot); the review therefore inspected feature-specific source guides and representative entry points rather than every file. No local checkout, dependency scan, or runtime tests were performed for this report.

## Executive summary

NextOrca already has a credible, distinctive core: a Python-first coding agent with a single terminal workflow, workspace-scoped file tools, explicit diff approval and checkpoints, approved shell execution, persistent SQLite sessions, Agent Skills, local plugin tools, MCP integrations, goal verification with a separate read-only reviewer, streaming, context compaction, and local/cloud routing with a hard local-only privacy mode.

Atomic Agent is broader than a terminal coding agent. Its CLI and full-screen TUI are one surface among several: it also provides a desktop sidecar, browser automation, managed local model lifecycle, broad provider adapters (including Claude/Codex subscription CLIs), durable memory, scheduled/background tasks, remote channels, HTTP/NDJSON interfaces, a plugin marketplace, and a large OS/document tool catalogue. It has a much more mature interaction shell and integration ecosystem, but those features also imply a much larger dependency, runtime, and maintenance footprint.

**Recommendation:** do not turn NextOrca into a feature-for-feature Atomic Agent clone. The NextOrca roadmap already identifies the highest-value gaps for its personal terminal-agent scope. Prioritise (1) a proper full-screen terminal experience, (2) session discovery/search and one-command resume, (3) a deliberate provider adapter expansion, and (4) a small, privacy-preserving cross-session memory capability only after the session UX is in place. Defer desktop, browser control, remote chat channels, scheduled autonomous work, media generation, and Atomic's extensive OS integrations until a concrete personal workflow justifies them.

## Comparison matrix

Legend: **Implemented** = supported by code and/or current product docs in NextOrca; **Partial** = analogous foundation exists but feature depth or UX differs; **Gap** = no comparable first-party feature was found during this audit; **Defer** = intentionally outside the recommended scope for now.

| Capability | NextOrca | Atomic Agent | Assessment for NextOrca |
|---|---|---|---|
| Core agent loop / tool use | Python runtime with registered tools, iterative tool calls, streaming and bounded turn/tool budgets | TypeScript agent loop, step/batch execution, runtime and multiple frontends | **Implemented**; keep NextOrca's lean single-agent loop |
| Terminal interaction | Line-oriented interactive REPL using `input()`, natural-language turns and slash commands | Full-screen Ink/React TUI, chat/session rail, composer, modals, keyboard/mouse navigation; CLI also offers run/debug commands | **Gap / P1**; best immediate user-facing improvement |
| One-shot CLI | Positional prompt; one-shot mode is read-only by default | `atomic-agent run` supports interactive stdin turns and one-shot piped prompts | **Implemented**, with intentionally safer one-shot default |
| Workspace file operations | Read/Glob/Grep; diff-preview Write/Edit; workspace confinement; checkpoints and guarded undo | Large typed filesystem tool family: read/write/edit, move, trash, patch, diff, hash, watch, archive and document parsing | **Partial**; current core is enough for basic coding; selectively add operations from actual project demand |
| Shell / process execution | Interactive Shell tool asks approval for exact command; runs with user's OS permissions; command timeout/output caps | Direct-exec/shell interpretation, environment filtering, process tooling, worktree sandbox support and multi-level approval | **Partial**; improve cancellation/process-tree cleanup before broadening autonomy |
| Approval and safety | Read-only default, per-mutation approval with visible preview; edits use diff approval; MCP per-call approval; MCP uses Linux Bubblewrap and fails closed | Layered approval categories/rules, scoped grants, read scopes, browser action/secret gates, plugin install review | **Implemented core, narrower policy surface**; preserve default-deny and add controls only alongside new capabilities |
| Checkpoints / undo | SQLite checkpoints; safe undo refuses files changed after checkpoint | Git worktrees/sandbox and patch/restore tools provide alternative recovery paths | **Implemented**; retain the simple explicit checkpoint model |
| Persistent sessions | SQLite messages/events, stable session IDs, workspace binding, resumable via `--session-id`; local metrics | Session store, rich TUI session rail, session titles, multiple frontends and durable task associations | **Partial**; storage foundation exists, discovery UX does not |
| Session search / browser | No CLI session list/search/browser was found; resume requires explicit ID | TUI session rail and session navigation, session commands and richer state | **Gap / P1**; expose existing session data before adding complexity |
| Context compaction | Character-budget pruning plus append-only model-generated summaries; transcript retained in SQLite | Bounded externalised world/session state, prompt slicing, compaction variants and explicit context controls | **Partial**; NextOrca has a good baseline; token-aware reporting and retrieval are potential follow-ons |
| Cross-session memory / recall | No distinct profile/fact store, note retrieval, reflection, embedding search or cross-session memory surface found | Durable memory fabric: structured profile facts, searchable notes, retrieval/context provider, reflection/consolidation, optional embeddings and TUI browsing | **Gap / P2 exploration**; design a smaller coding-project memory, not a wholesale port |
| Goal / task completion | GoalRunner: worker completion signal, optional approved verification, separate read-only reviewer, persisted state and bounded retries | Criteria-based goals, repeated rounds/checks, durable tasks, retry/resume, scheduler and overnight execution | **Partial**; NextOrca already has verification/review; scheduler is a separate feature |
| Skills | Agent Skills folder convention, project/user discovery, metadata catalog and on-demand body loading | Skill install/manage/import, packaged starter skills, project trust and plugin skill sources | **Implemented core / partial management UX**; build on standard format |
| Plugins | Local declarative JSON bundles with skills and argv command tools; approval required; no arbitrary Python imports | Rich Claude/Codex/Cursor-style plugin formats, install review, permission diff, enable/disable, marketplaces, slash commands, hooks and MCP; plugin subagent profiles are listed but docs say they do not run yet | **Partial**; improve ergonomic management only if it helps daily use; marketplace is not a priority |
| MCP | Experimental stdio, explicit configuration, per-call approval, strict schema checks, Linux Bubblewrap isolation | MCP client, plugin/user MCP servers, TUI management and broader runtime integration | **Implemented core / partial UX**; keep the fail-closed sandbox policy |
| Provider support | One `OpenAICompatibleProvider` supports compatible local/hosted endpoints; `ChatProvider` and optional streaming protocols are defined; HybridRouter composes the same provider implementation | Provider registry/adapters for OpenAI-compatible, OpenRouter, Gemini, aimlapi, llama-server and Claude/Codex subscription CLIs; strict tool schemas, tagged tool-call compatibility and provider-specific behavior | **Partial / P2**; leverage the existing protocol and add adapters deliberately |
| Local model lifecycle | Connects to external OpenAI-compatible local endpoint (e.g. llama.cpp); no managed download/server process found | Managed Atomic Core/llama.cpp lifecycle, model catalog, downloads, GPU selection and backend management | **Gap, but defer**; model lifecycle is a separate product subsystem and can remain external |
| Browser automation | No browser tool/backend found | Playwright/Chromium browser tools: navigate, tabs, click, type, ARIA views, screenshots, domain controls, own-Chrome attach and sensitive action approvals | **Gap, defer**; major dependency and safety surface, not required by current roadmap |
| Web / research tools | No dedicated first-party web search/fetch tool found; shell and MCP can be extended | First-party web search/fetch and browser research workflow | **Gap, defer or plugin**; only prioritise if repository work regularly needs live docs/research |
| Remote channels | No Telegram/Discord/HTTP remote channel found | Telegram/Discord adapters, approval bridges, HTTP API and NDJSON sidecar | **Gap, defer**; remote control changes the security and deployment model |
| Desktop app / sidecar | Python CLI only; no desktop/Tauri integration | Tauri desktop integration using NDJSON sidecar | **Gap, defer**; outside terminal-only product definition |
| Durable schedules / overnight work | Interactive goals; no durable scheduler or cron queue found | Persistent task queue, schedules/webhooks, retry and interrupted-task resume, overnight task with caps | **Gap, defer**; add only for a clear unattended workflow |
| Parallel subagents | Single worker + independent reviewer in goal mode; no bounded parallel worker pool found | Fusion mode with bounded worker pool and policy-filtered tools | **Gap / later**; requires robust cancellation, resource budgets and isolation first |
| Import / interoperability | Reads standard Agent Skills and local plugin format; no session importer found | Import from other agents, handoff from Claude/Codex sessions, broad plugin compatibility | **Partial / later**; standard skills already provide the most useful small interoperability seam |
| Observability | Local session metrics for provider, latency, token usage and routing; verbose events | Structured traces, replay, broad metrics, debug bundles and TUI observations | **Partial**; strengthen only around concrete debugging questions |
| Evaluation | Deterministic routing eval with threshold and unit/integration tests | Broad testing/CI plus agent, memory and GAIA-style evaluation harnesses | **Partial**; add repeatable coding-task benchmarks when comparing model/routing changes |

## What NextOrca already does well

1. **Focused identity.** `docs/ROADMAP.md` explicitly describes NextOrca as a personal terminal coding agent; commercial readiness and Vercel deployment are out of scope. Its product definition says local/cloud orchestration must remain behind one agent experience.
2. **Safety in the core workflow.** Interactive file writes are previewed and approved, checkpoints support guarded undo, one-shot stays read-only, and MCP cannot silently run without its configured Linux sandbox. This is an appropriate foundation for a personal coding agent.
3. **Portable extension points.** Standard Agent Skills, local declarative plugins, MCP stdio, and the existing provider protocols allow useful integrations without adopting Atomic's much larger runtime architecture.
4. **Goal verification rather than “looks done”.** NextOrca's goal mode runs an optional approved verification command and a fresh read-only reviewer. This is an important differentiator to preserve as the agent becomes more capable.
5. **Privacy-aware hybrid routing.** The local-only mode is an explicit hard boundary, not just a preference hint; local provider failure does not authorise cloud fallback.

## Prioritised findings

| ID | Finding | Category | Impact | Effort | Risk | Confidence | Recommendation |
|---|---|---|---|---|---|---|---|
| F-01 | The line-oriented REPL is the main interaction bottleneck compared with Atomic's full-screen TUI | direction / dx | High: navigation, approvals, context status and session switching are text-command based | L | MED | HIGH | **P1: build a full-screen TUI**, retaining the current REPL as a stable fallback |
| F-02 | Durable session data exists but is not discoverable | dx | High: users need to manually preserve and supply a session ID to continue prior work | M | LOW | HIGH | **P1: add session listing, filtering/search and resume selection** |
| F-03 | Provider protocol seam exists, but CLI wiring instantiates only OpenAI-compatible transport | direction / dx | Medium: adding a provider requires adapter and config selection work; provider-specific capabilities are unavailable | M | MED | HIGH | **P2: add a provider registry/adapter boundary and one selected native adapter after a focused design decision** |
| F-04 | Context compaction is not cross-session memory | direction / perf | Medium: summaries help a single session continue, but facts/decisions learned in other sessions are not independently retrievable | M/L | MED | HIGH | **P2: design a small, local-only project memory with explicit inspect/delete controls** |
| F-05 | NextOrca does not manage local inference server/model lifecycle | direction | Medium for users who want an integrated local setup; low if they already operate llama.cpp/other server | L | HIGH | MED | Defer; keep external OpenAI-compatible endpoint as the boundary until there is a concrete need |
| F-06 | Browser automation is a substantial missing capability | direction / security | Potentially high for web-oriented tasks, but adds a large browser dependency, profile/credential boundary, page-content threat model and action approval system | L/XL | HIGH | HIGH | Defer; do not import Atomic's browser subsystem without an explicit browser-use requirement |
| F-07 | Durable schedules, remote channels, desktop sidecar and autonomous overnight runs are absent | direction / security | These introduce unattended execution, remote identity, network ingress and new data/control boundaries | L/XL | HIGH | HIGH | Defer as a separate product direction |
| F-08 | No bounded parallel subagent orchestration or reproducible real-repository task benchmark was found | direction / perf | Parallelism may help larger tasks, but increases cost, context, merge conflicts and permission/cancellation complexity; benchmark evidence is needed | M/L | HIGH | HIGH | Defer until cancellation/process cleanup and real-repo evaluations are established |
| F-09 | Atomic's broad first-party filesystem/document/OS tool catalogue is not present | dx | Some workflows would be easier with dedicated document, archive, git, diff/patch or process/window tools; shell/plugins/MCP already provide an extension route | M/L | MED | HIGH | Add individual tools only from repeated use cases, not for feature-count parity |

## Recommended implementation sequence

The first four plans are intentionally narrower than Atomic's feature inventory. Each should land in its own PR, preserve the lightweight PR CI policy, and avoid changing more than one major user-facing surface at a time.

| Plan | Priority | Title | Effort | Depends on | Outcome |
|---|---:|---|---:|---|---|
| 005 | P1 | Add a full-screen terminal workspace without removing the REPL | L | none | Interactive chat, clear turn/tool status, approvals, session navigation, and graceful fallback in a full-screen terminal UI |
| 006 | P1 | Make persisted sessions discoverable and resumable | M | none | Workspace-scoped session list, recent activity, search/filter and one-command resume before TUI depends on it |
| 007 | P2 | Introduce a deliberate provider adapter registry and first additional adapter | M | none | Keep `ChatProvider` semantics and routing; add a second protocol only after selecting a target/provider contract |
| 008 | P2 | Design and prototype bounded cross-session project memory | M | 006 | Local-only facts/decisions retrieval with transparent provenance, inspect/delete controls and bounded prompt budget |

Plan 006 is deliberately ahead of the TUI implementation in conceptual ownership even though both can be implemented independently: the TUI should consume a stable session service rather than own SQLite queries. Plan 008 depends on 006 because memory should associate facts with project/session context and expose provenance without compromising existing session isolation.

## Explicitly deferred / rejected for this project scope

- **Browser automation and own-Chrome attach:** defer. A browser is not a coding-agent prerequisite and would require dedicated browser-profile, secret-field, page prompt-injection and action-classification controls.
- **Tauri desktop application and sidecar API:** defer. They add another product surface and protocol lifecycle; the current product definition is a terminal agent.
- **Telegram/Discord, HTTP remote control, webhooks:** defer. These require remote identity/pairing, ingress authentication, approval bridging and channel-specific secret handling.
- **Durable scheduled/overnight autonomy:** defer. Interactive `/goal` with verification is sufficient until a concrete unattended work queue is needed.
- **Managed local model downloads/server orchestration:** defer. NextOrca intentionally consumes an external OpenAI-compatible endpoint; model lifecycle can be handled by llama.cpp or another local server.
- **Media generation, email, broad desktop/OS control, document-format catalogue:** defer; not central to editing and verifying source repositories.
- **Plugin marketplace and support for every plugin ecosystem:** defer. Local declarative plugins, Agent Skills and MCP already provide extensibility with a much smaller trust surface.
- **Parallel subagents:** defer until cancellation/process-tree handling, per-worker tool/permission boundaries, resource caps and real-repo evaluation are mature.
- **GAIA benchmark parity:** do not add a vanity score. Build a small repeatable coding benchmark from real project tasks and score successful verified changes, not unrelated general-assistant benchmarks.

## Evidence and source map

### NextOrca (audited default branch)
- [README / feature list](https://github.com/ahmedaisar/NextOrca/blob/main/README.md)
- [Product roadmap and explicit personal-project scope](https://github.com/ahmedaisar/NextOrca/blob/main/docs/ROADMAP.md)
- [CLI assembly and provider wiring](https://github.com/ahmedaisar/NextOrca/blob/main/nextorca/cli.py)
- [REPL and supported slash commands](https://github.com/ahmedaisar/NextOrca/blob/main/nextorca/repl.py)
- [Provider protocols](https://github.com/ahmedaisar/NextOrca/blob/main/nextorca/provider.py)
- [OpenAI-compatible provider](https://github.com/ahmedaisar/NextOrca/blob/main/nextorca/openai_compatible.py)
- [Hybrid local/cloud routing](https://github.com/ahmedaisar/NextOrca/blob/main/nextorca/routing.py)
- [Persistent session store](https://github.com/ahmedaisar/NextOrca/blob/main/nextorca/session_store.py)
- [Goal mode](https://github.com/ahmedaisar/NextOrca/blob/main/nextorca/goals.py)
- [Skills guide](https://github.com/ahmedaisar/NextOrca/blob/main/docs/skills.md)
- [Plugins guide](https://github.com/ahmedaisar/NextOrca/blob/main/docs/plugins.md)
- [Routing guide](https://github.com/ahmedaisar/NextOrca/blob/main/docs/routing.md)
- [Package and test configuration](https://github.com/ahmedaisar/NextOrca/blob/main/pyproject.toml)
- [Lightweight PR / scheduled comprehensive CI](https://github.com/ahmedaisar/NextOrca/blob/main/.github/workflows/ci.yml)

### Atomic Agent (reference repository)
- [README / user-facing feature claims](https://github.com/AtomicBot-ai/atomic-agent/blob/main/README.md)
- [CLI command map](https://github.com/AtomicBot-ai/atomic-agent/blob/main/src/cli/index.ts)
- [TUI feature map](https://github.com/AtomicBot-ai/atomic-agent/blob/main/src/tui/README.md)
- [Browser tools and approval model](https://github.com/AtomicBot-ai/atomic-agent/blob/main/src/tools/browser/README.md)
- [Provider adapters / subscription CLI implementations](https://github.com/AtomicBot-ai/atomic-agent/tree/main/src/llm/provider)
- [Managed local inference lifecycle](https://github.com/AtomicBot-ai/atomic-agent/blob/main/src/local-llm/README.md)
- [Durable memory architecture](https://github.com/AtomicBot-ai/atomic-agent/blob/main/src/memory/README.md)
- [Durable tasks and scheduling](https://github.com/AtomicBot-ai/atomic-agent/blob/main/src/tasks/README.md)
- [Channels](https://github.com/AtomicBot-ai/atomic-agent/blob/main/src/channels/README.md)
- [Plugins and marketplaces](https://github.com/AtomicBot-ai/atomic-agent/blob/main/src/plugins/README.md)
- [Tool catalogue](https://github.com/AtomicBot-ai/atomic-agent/blob/main/src/tools/README.md)
- [Package scripts and dependencies](https://github.com/AtomicBot-ai/atomic-agent/blob/main/package.json)

## Audit limitations

- This audit records capabilities found in current repo source/docs; it does not independently validate all edge cases or platform support.
- Atomic's README and source tree are very large. Selected feature modules and their docs were inspected; not all 4,120 tracked paths were read.
- No executable tests, interactive usability checks, model/provider calls, performance benchmarks, dependency vulnerability scans, or cross-platform trials were run.
- Feature presence does not imply the feature is enabled by default, works on every OS, or is comparable in quality to NextOrca.
- No source code in either repository was modified for this audit.
