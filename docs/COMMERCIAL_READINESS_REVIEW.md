# Commercial Readiness Review and EARS Plan

**Repository:** https://github.com/ahmedaisar/NextOrca  
**Baseline:** main @ b185a4198e4a3a2d8655120513326d8b1b487872  
**Review date:** 2026-11-08  
**Scope:** tracked source, scripts, setup, examples, packaging and public documentation. This is a source review, not a runtime benchmark.

## Executive assessment

NextOrca demonstrates a valuable hybrid inference pattern: a cloud model acts as the primary coding agent while a small local model explores a codebase, with cloud fallback on context/turn limits. The repository is currently an experimental proxy and batch-analysis harness, not an independent coding-agent platform. Preserve its core local-specialist/cloud-orchestrator concept, but evolve it into a provider-independent, permissioned agent runtime.

**Recommendation:** do not commercialize the current proxy as-is. Build a local-first, terminal-first runtime with a stable model interface, strict tool contracts, explicit approval policy, durable sessions and measurable routing. Defer hosted team control plane, GUI and marketplace until the core execution model is reliable.

## Inventory

- `scripts/proxy.py`: custom HTTP server, Anthropic-shaped ingress, local llama.cpp OpenAI-compatible endpoint, OpenRouter fallback, hand-written protocol conversion and tool tag parsing.
- `scripts/setup.sh`: loads .env and generates Claude Code settings.
- `scripts/start_services.sh`: starts llama-server and proxy.
- `scripts/analyze.sh`, `scripts/test_single.sh`: batch/single analysis via `claude -p`.
- `examples/*.py`: Transformers model loading/inference snippets.
- `LocoOperator_4B.ipynb`: model notebook companion.
- `data/queries`, `prompts`: fixed benchmark tasks and prompt template.
- `pyproject.toml`: minimal Python project; no test/dev/lint setup.
- `.env.example`: one OpenRouter key placeholder.

The README describes LocoOperator-4B as an exploration sub-agent, not a full coding agent. The existing Claude Code loop supplies most of the actual agent experience.

## Pros

1. **Specialization:** local model targets exploration and tool choice, a lower-risk workload than unrestricted edits.
2. **Cost/privacy potential:** repository navigation can remain on-device and reduce paid cloud tokens.
3. **Fallback concept:** local context/turn exhaustion can escalate to a stronger remote model.
4. **Low prototype footprint:** Python, httpx, llama.cpp and OpenRouter are easy to experiment with.
5. **Evaluation seed:** README reports tool-call presence, first-tool alignment and JSON/argument validity on 65 samples from varied repositories.
6. **Reasonable model positioning:** documentation acknowledges limitations and read-only specialization rather than claiming autonomous coding competence.

## Cons and risks

### P0 — correctness, safety and operational blockers

- **Unsafe execution default:** shell runners use `--dangerously-skip-permissions`. A commercial product needs least privilege, per-tool policy, approval UX and a sandbox.
- **Secret handling:** setup serializes the OpenRouter API key into generated `.claude/settings.local.json`; parsing .env and interpolating arbitrary key text into JSON is fragile. Secrets should remain in environment/OS secret storage and be redacted.
- **Protocol conversion is lossy:** the converter flattens message blocks into text, injects a fixed system prompt, and does not preserve full tool schemas, tool-use/result IDs, images, cache controls, metadata, thinking or all stop/error semantics.
- **Malformed tool calls silently disappear:** JSON failures in the parser are swallowed, making a failed tool action appear as an ordinary final answer. Tool names/arguments are not validated against registered schemas.
- **Streaming is synthetic:** local request uses `stream=False`; an SSE-shaped response is assembled only after generation completes. Usage is fabricated as zero in that path.
- **Single-threaded/unbounded HTTP:** `HTTPServer`, large client timeouts, unbounded Content-Length, no concurrency/queue limit, no auth/rate control, no request IDs or cancellation. A slow inference request can block all traffic.
- **Error leakage:** raw exception strings may be exposed to clients; no structured redaction or stable error taxonomy.
- **Brittle fallback:** assistant-message count is used as a turn proxy; only one context-overflow error shape triggers fallback. No clear retry taxonomy, circuit breaker, latency/cost budget or duplicate-side-effect guard.
- **Hard-coded configuration:** endpoints, ports, model IDs and turn limit are constants rather than validated config.
- **Lifecycle concerns:** startup scripts have a sourced-file trap and a fixed sleep instead of verified readiness; ownership of launched processes and cleanup paths need tests.
- **Batch accounting:** a background job can exit successfully without creating the expected output file, yet be counted as successful. Batch-size input is not validated.

### P1 — product and engineering gaps

- No first-party agent loop, tool registry, provider abstraction, context compaction, cancellation, resumability or structured event stream. Claude Code performs most orchestration.
- No session store, git checkpoint, diff review, undo/redo or audit log.
- No workspace boundary or symlink-aware path checks.
- No versioned plugins, MCP, skills, subagents or custom agent definitions.
- No reproducible cross-platform packaging; shell scripts assume Unix tools and an external Claude CLI.
- No lockfile, CI, unit/integration/security tests, formatting/type checks or release workflow.
- No deterministic benchmark harness, independent ground truth, edit/test tasks, pass rate, latency/cost metrics or confidence intervals. 65 teacher-labeled examples are an exploratory signal, not production evidence.
- No privacy/data-flow docs, threat model, model/license compatibility, retention policy, telemetry policy or support diagnostics.
- No clear model capability discovery or hardware-aware local model selection.

### P2 — commercial scaling gaps

No identity/team/org layer, billing/metering, quotas, cost allocation, managed credentials/policy, enterprise SSO/SCIM, audit export, retention management, signed releases, SBOM, vulnerability process, support SLA or privacy-safe product analytics.

## Competitive architecture implications

### OpenCode
Its public feature set includes terminal/desktop/mobile clients, SDK, multiple providers, multi-session operation, plugins, MCP, custom agents, skills/commands and permissions. The key lesson is that permission controls and session management are product foundations, not model add-ons.

### Pi
Pi demonstrates a composable approach: model/provider API, agent loop/tool execution, terminal UI and coding-agent shell, with a deliberately narrow built-in tool set and extension points. The lesson is to keep the core small and typed, with extensions outside core.

### NextOrca differentiation
A potential wedge is **hybrid inference with local-first code intelligence**: keep bounded repository mapping, symbol lookup, retrieval, summarization and repetitive low-risk tasks local; escalate ambiguous planning, complex edits/debugging and tasks needing stronger reasoning. Make routing policy configurable and explainable, rather than a hard-coded model alias and message-count threshold.

## Target architecture

1. **Application shell:** terminal-first interactive client plus headless/JSON/RPC and embeddable SDK.
2. **Agent runtime:** event-driven loop with turn states, cancellation, retries, tool budgets, context compaction and resumability.
3. **Provider/model layer:** typed request/response/stream contract; adapters for Anthropic Messages, OpenAI Responses/Chat Completions, OpenRouter, llama.cpp, Ollama and compatible endpoints.
4. **Routing engine:** task class + capability fit + privacy + latency/cost + provider availability; reasoned route decisions and manual override.
5. **Tool runtime:** typed schemas, registry, read/glob/grep/edit/write/bash/git/test tools, bounded output, timeouts and deterministic errors.
6. **Permission/sandbox:** deny/ask/allow policy, approval for mutation and shell execution, project/path boundaries, secret protection, sandbox/container option and audit trail.
7. **Workspace layer:** canonical root, symlink-aware path checks, git diff/checkpoints, worktrees and rollback.
8. **Session/context:** SQLite-backed conversation/event log, prompt budgets, output pruning, summary checkpoints and export/import.
9. **Extension layer:** versioned tools, hooks, subagents, SKILL.md workflows, MCP client, templates and themes. Extensions cannot bypass permissions.
10. **Commercial control plane (later):** org policy, identity/SSO, billing, quotas, managed credentials, audit, retention and fleet config. Local CLI must remain usable offline.

## EARS requirements

Patterns: **Ubiquitous** (The system shall...), **Event-driven** (When...), **State-driven** (While...), **Unwanted behavior** (If...), and **Optional feature** (Where...). Acceptance criteria are testable.

### Phase 0 — safety and reliability (P0)

- **REQ-001 — Safe execution (Ubiquitous):** The system shall require explicit approval before shell commands or workspace mutations unless a narrowly scoped allow rule exists. **Acceptance:** default bash/write/edit policy is ask or deny; read tools may be allowed separately; no shipped path bypasses approvals.
- **REQ-002 — Workspace confinement (Ubiquitous):** The system shall constrain file tools to the configured workspace and reject traversal and symlink escapes. **Acceptance:** tests cover absolute paths, `..`, symlink escape, nonexistent paths and normalization.
- **REQ-003 — Typed tool calls (Event-driven):** When a model emits a tool call, the runtime shall validate its registered name and JSON schema before execution. **Acceptance:** malformed JSON, unknown tools, missing required fields and wrong types return typed errors and never invoke the tool.
- **REQ-004 — Protocol fidelity (Ubiquitous):** Provider adapters shall preserve supported roles, tool IDs/results, structured content, stop reasons and usage. **Acceptance:** fixture round-trip tests cover text, multi-tool calls, tool results, unsupported/image blocks and errors.
- **REQ-005 — Honest streaming (Event-driven):** When streaming is requested, the runtime shall forward provider events incrementally or explicitly indicate a non-streaming adapter. **Acceptance:** event sequence matches protocol; partial tool JSON is safely accumulated; completed-response SSE is not misrepresented as live.
- **REQ-006 — Bounded service (Ubiquitous):** The local API shall cap request size, concurrency, queue, timeout and output size. **Acceptance:** overload and oversized requests return stable errors; slow inference cannot block health/readiness endpoints or unrelated requests.
- **REQ-007 — Secret hygiene (Ubiquitous):** The system shall load credentials from environment or OS secret storage and shall not write plaintext secrets to generated project settings or logs. **Acceptance:** tests assert settings output contains no API key; redaction tests cover key-shaped strings.
- **REQ-008 — Safe fallback (Event-driven):** If local inference fails, times out or overflows context, routing shall apply configured escalation without replaying already-executed side effects. **Acceptance:** fault-injection tests cover timeout, 429, 5xx, invalid response, context overflow and unavailable local provider.
- **REQ-009 — Validated configuration (Event-driven):** When the process starts, it shall validate provider URLs, model IDs, timeouts, budgets and policy before serving. **Acceptance:** invalid config fails fast with actionable, redacted diagnostics.
- **REQ-010 — CI and regression baseline (Ubiquitous):** The repository shall run automated tests, lint and supported Python-version checks on pull requests. **Acceptance:** CI executes unit tests plus lint checks and blocks failures.

### Phase 1 — independent coding runtime (P1)

- **REQ-011 — Agent loop (Ubiquitous):** The runtime shall orchestrate model responses, tool calls and follow-up turns without depending on Claude Code. **Acceptance:** a headless task can explore, edit a fixture repository, run tests under approval and report results.
- **REQ-012 — Provider abstraction (Ubiquitous):** The runtime shall expose a stable provider interface and select models using declared capabilities. **Acceptance:** contract tests run against mocked Anthropic, OpenAI-compatible and local providers.
- **REQ-013 — Durable sessions (Event-driven):** When a session event occurs, the runtime shall append it to durable storage and recover unfinished sessions after restart. **Acceptance:** restart/resume tests preserve message and tool order plus metadata.
- **REQ-014 — Context budget (State-driven):** While a conversation approaches a model's usable context budget, the runtime shall prune redundant tool output or checkpoint a summary. **Acceptance:** tests preserve recent user intent, key decisions and tool provenance.
- **REQ-015 — Hybrid routing (Event-driven):** When a task is classified, the router shall select a local/cloud model using capability, privacy, latency, cost and availability policy. **Acceptance:** route records selected provider, rationale and fallback; the user can override it.
- **REQ-016 — CLI modes (Ubiquitous):** The product shall expose interactive, print and machine-readable modes with consistent runtime behavior. **Acceptance:** CLI supports workspace, model/provider, permissions, JSON events and headless operation.
- **REQ-017 — Workspace recovery (Event-driven):** When a mutation is approved, the runtime shall checkpoint state and show the resulting diff before completion. **Acceptance:** undo restores supported changes and rollback failure is reported.
- **REQ-018 — Observability (Ubiquitous):** The runtime shall expose structured, redacted per-turn token, latency, tool and estimated-cost metrics. **Acceptance:** metrics work without external services and can be disabled.

### Phase 2 — extensibility and scale (P1/P2)

- **REQ-019 — Extensions (Where enabled):** Where an extension is enabled, the runtime shall load versioned tools/agents under core policy enforcement. **Acceptance:** incompatible extensions fail in isolation and cannot elevate permissions.
- **REQ-020 — MCP (Where configured):** Where an MCP server is configured, the runtime shall discover tools with timeouts, schema bounds and per-server permissions. **Acceptance:** server failure does not crash sessions; approval identifies server and tool.
- **REQ-021 — Subagents (Where enabled):** Where subagents are enabled, each child shall receive bounded task, model, context and permissions. **Acceptance:** depth/concurrency limits apply; child scope cannot exceed parent scope.
- **REQ-022 — Parallel sessions (Event-driven):** When sessions edit the same repository concurrently, the runtime shall isolate them in worktrees or detect conflicts explicitly. **Acceptance:** integration tests prove branch/worktree isolation and actionable conflict reporting.
- **REQ-023 — Cross-platform distribution (Ubiquitous):** The product shall provide reproducible installs and updates for Linux, macOS and Windows. **Acceptance:** OS CI builds pass and signed release artifacts are available.

### Phase 3 — commercial operations (P2)

- **REQ-024 — Admin policy (Where managed workspace enabled):** Where managed workspaces are enabled, administrators shall set model allowlists, data boundaries, tool permissions and retention. **Acceptance:** policy is enforced locally with documented offline behavior.
- **REQ-025 — Metering and quotas (Event-driven):** When provider requests complete, the system shall meter provider/model/tokens/latency/cost estimate against user/team quotas. **Acceptance:** usage writes are idempotent and budget exhaustion is tested.
- **REQ-026 — Enterprise identity/audit (Where enterprise tier enabled):** Where enterprise functionality is enabled, the service shall support SSO, role-based access, audit export and retention controls. **Acceptance:** threat-model review and integration tests precede GA.
- **REQ-027 — Privacy routing (Ubiquitous):** The product shall disclose and enforce which source, prompt and tool data leave the device for each route. **Acceptance:** local-only mode has network-egress tests; cloud requests expose a clear transmission boundary.
- **REQ-028 — Release governance (Ubiquitous):** The project shall publish a supported-version policy, dependency inventory, vulnerability contact and signed releases. **Acceptance:** release pipeline emits SBOM, checksums/signatures and provenance.

## Prioritized delivery

1. Secure baseline: permissions, path safety, schema validation, secret hygiene, bounded API, tests.
2. Runtime core: provider interface, typed tools, independent agent loop and events.
3. Developer UX: CLI, durable sessions, diff/undo and compaction.
4. Hybrid intelligence: router, local specialist, cloud escalation and reproducible evaluations.
5. Extensions/concurrency: MCP, skills, subagents and worktree isolation.
6. Commercial operations: identity, quotas, managed policy, audit and enterprise packaging.

## Optimization recommendations

- Do not route every tool turn to a small model. Reserve local inference for retrieval, repository mapping, classification and compact summaries; escalate edits, debugging and uncertainty when expected value is higher.
- Route by task class and measured capability, not assistant-message count. Track quality, latency, cost and escalation per class.
- Prefer ripgrep/glob/AST/LSP retrieval before generation; provide bounded, line-numbered context with provenance rather than whole files.
- Enforce output/context budgets, deduplicate snippets, prune stale tool output and persist summaries.
- Parallelize independent read-only search; serialize conflicting writes and cap local inference concurrency based on available GPU memory.
- Instrument route reason, tokens, queue time, latency, retries, context overflow, schema validity, approval delay and task outcome.
- Build reproducible repository issue/edit/test benchmarks with independent assertions, blind model comparisons and cost/latency distributions. Teacher-labeled tool-choice accuracy is not a product KPI.
- Keep the local CLI usable offline. Hosted services should add governance/collaboration/billing rather than gate core execution.
- Treat repository files, browser results, tool output and MCP data as untrusted content that cannot override system policy; enforce least privilege and explicit approvals.

## First implementation boundary

This PR adds the architecture/EARS assessment. Runtime changes are deliberately split into separate, test-backed PRs. The project has no existing runtime test harness, so no end-to-end validation is claimed here. Real llama.cpp/OpenRouter integration, model licensing checks, threat modeling and independent security review remain prerequisites for commercial release.
