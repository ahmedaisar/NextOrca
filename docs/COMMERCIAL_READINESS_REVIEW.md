# Commercial Readiness Review and EARS Plan

**Repository:** [ahmedaisar/NextOrca](https://github.com/ahmedaisar/NextOrca)  
**Reviewed baseline:** `main` at `b185a4198e4a3a2d8655120513326d8b1b487872`  
**Review date:** 2026-11-08  
**Scope:** source, scripts, setup, examples, packaging, public docs and reference-product architecture. This is a source review, not a runtime benchmark; the repository does not include a test suite or a reproducible local model fixture.

## Executive assessment

NextOrca demonstrates an interesting hybrid inference pattern: a cloud model acts as the primary coding agent while a small local model is used for code exploration, with fallback to a cloud model on context/turn limits. The repository's implementation is currently an experimental proxy and batch-analysis harness, not a standalone coding-agent product. Its most valuable asset is the local-specialist + cloud-orchestrator split. Preserve that as a policy-driven capability inside a model-agnostic runtime.

**Recommendation:** do not attempt to commercialize the existing proxy as-is. Build a local-first, terminal-first coding-agent runtime with a stable provider interface, strict tool contracts, explicit approval policy, reproducible sessions, and testable routing. Treat hosted/team control plane, GUI, marketplace and autonomous multi-agent execution as later phases.

## Inventory and current-state map

The repository is small and Python-centric:

- `scripts/proxy.py`: custom HTTP server, Anthropic-shaped request endpoint, local llama.cpp OpenAI-compatible endpoint, OpenRouter remote fallback, hand-written protocol conversion and tool tag parsing.
- `scripts/setup.sh`: reads a .env key and generates Claude Code local settings.
- `scripts/start_services.sh`: launches llama-server and proxy and traps cleanup.
- `scripts/analyze.sh`, `scripts/test_single.sh`: batch/single analysis driven by `claude -p`.
- `examples/*.py`: Hugging Face Transformers loading/inference examples.
- `LocoOperator_4B.ipynb`: model notebook/training or evaluation companion.
- `data/queries`, `prompts`: fixed benchmark tasks and prompt template.
- `pyproject.toml`: minimal Python project with httpx and python-dotenv; no declared test/dev/lint setup.
- `.env.example`: single OpenRouter API key placeholder.

The README describes the model as an exploration sub-agent (not a full coding agent), and the pipeline delegates local exploration while cloud Claude Code remains the main agent. The actual proxy maps all Anthropic message history into one textual system/message representation for local inference.

## Pros

1. **Clear specialization:** local model is focused on exploration/tool selection, a workload with lower risk than unrestricted edits.
2. **Cost/privacy leverage:** local inference can keep routine repository navigation on-device and reduce paid cloud tokens.
3. **Fallback concept:** local context/turn exhaustion can move work to a stronger remote model.
4. **Low infrastructure footprint:** Python + httpx + llama.cpp + OpenRouter are easy to prototype and self-host.
5. **Evaluation seed:** the README documents tool-call presence, first-tool alignment and JSON/argument validity, plus a diverse sample of public codebases.
6. **Good scope discipline in model positioning:** documentation acknowledges the model is a read-only explorer rather than claiming it is a production autonomous coder.

## Cons and risks

### P0 — correctness, safety and operational blockers

- **Unsafe execution default:** both shell runners pass `--dangerously-skip-permissions`. This is unacceptable as a commercial default; no per-tool policy, approval UX, path boundary, command classification or sandbox is implemented in this repository.
- **Remote key exposure in generated settings:** `setup.sh` writes the OpenRouter key into `.claude/settings.local.json`. This broadens secret-at-rest exposure and uses a fragile shell parser/JSON interpolation. The generated file is not shown in the repository listing but its lifecycle and permissions need controlled management.
- **Protocol conversion loses semantics:** system prompts, tool definitions, tool IDs, tool results, images, cache controls, metadata, thinking and other Anthropic content are not faithfully represented in the local request. The proxy injects a hard-coded training prompt and does not translate declared tool schemas into a native tool-calling format.
- **Tool-call parser silently drops malformed calls:** JSON parse errors in `parse_tool_calls` are swallowed, turning a failed tool action into apparent assistant text/end-turn. Names and arguments are not validated against an allowlist/schema.
- **SSE is not truly streamed:** local inference is requested with `stream=False`; the proxy then emits a synthetic SSE stream after generation completes. Tool input deltas are emitted after a complete tool block and token accounting is fabricated as zero in the SSE path.
- **HTTP server is single-threaded and request handling is unbounded:** `HTTPServer`, 300-second clients, unbounded Content-Length/body parse, no authentication, no rate limits, no request IDs, no bounded concurrency/queue and no graceful timeout/cancellation. A stalled inference request can block all clients.
- **Error handling leaks internals:** exception strings are returned to clients and arbitrary upstream bodies/status handling are not normalized. No structured redaction or safe diagnostics.
- **Fallback is brittle:** hard-coded turn-count heuristic uses assistant-message count, which is not a reliable turn budget; only one specific local context error triggers fallback. No retry taxonomy, circuit breaker, health state, budget, latency or per-provider telemetry.
- **Configuration is hard-coded:** loopback URLs/ports/model IDs/max turns are constants; model routing is inferred from a small hard-coded model set. No validated config object or provider health checks.
- **Potential startup lifecycle bugs:** `start_services.sh` is documented as sourced, and has a global EXIT trap. It can kill services it did not start only if PIDs are set? Existing remote services are intentionally not assigned, but launched process health and cleanup ownership are not reliably tracked; proxy startup only sleeps and is not health-checked. In scripts that source it, EXIT trap interactions deserve tests.
- **Batch runner accounting:** background job exits can be counted as success based on the CLI exit code even when the expected output file is absent; output creation and per-query status are not atomically tied. Batch size is not validated as positive integer.

### P1 — product and engineering gaps

- No first-class agent loop, tool registry, provider abstraction, session state/store, context compaction, cancellation, resumability or structured event stream. Claude Code supplies most of the actual agent experience.
- No durable conversation/session model, branch/worktree isolation, checkpoints, diff review, undo/redo or audit log.
- No project-scoped file boundary or symlink-aware path guard.
- No pluggable tools/skills/MCP layer or custom agent definitions.
- No cross-platform packaging or tested Windows support; shell scripts assume Unix-like tooling and an external Claude CLI.
- No dependency pinning/lock, CI, unit/integration/security tests, formatting/type checks or release workflow.
- No deterministic benchmark harness, ground-truth labels independent of a teacher, regression corpus, realistic edit tasks, pass@1, latency/cost measurements or confidence intervals. 65 examples and teacher-generated labels are useful exploratory metrics, not evidence of production performance.
- No docs covering privacy/data flow, threat model, provider terms, model licensing, telemetry, retention, supported environments or troubleshooting.
- README's setup appears inconsistent: it mentions a clone/setup flow and describes repo paths and settings generation that are not fully represented by the tracked tree.
- Local model name/format/provider assumptions are embedded in the converter; no hardware-aware model discovery or capability metadata.

### P2 — commercial scaling gaps

- No account/team/org identity, billing metering, quotas, entitlement or cost allocation.
- No centralized policy/config distribution or managed provider credentials.
- No enterprise controls (SSO/SCIM, audit export, retention controls, private networking, key management, admin policy).
- No update channel, compatibility matrix, signed releases, SBOM, vulnerability response or support diagnostics.
- No extensibility/versioning contract for tools, plugins, model adapters or agents.
- No product analytics based on opt-in, privacy-safe aggregate metrics.

## Competitive architecture implications

### OpenCode
OpenCode's public product surface includes terminal/desktop/mobile, SDK, multi-session operation, provider breadth, plugins, MCP, custom agents, skills/commands and permission controls. Its documented permission model supports allow/deny/ask decisions, and agent roles can have different tool permissions. These are capabilities and user-trust mechanisms rather than merely model quality features.

### Pi coding agent
Pi emphasizes a small composable TypeScript architecture: provider/model APIs, agent loop and tool execution, terminal UI, and a coding-agent shell. Its minimal default tool set and extensions/skills/packages demonstrate that a narrow core with extension seams can scale better than a monolithic proxy.

### NextOrca's differentiation
A credible wedge is **hybrid inference with local-first code intelligence**: route repository mapping, symbol lookup, bounded read-only exploration, summarization and inexpensive repetitive tasks locally; route ambiguous planning, complex edits, test repair and cross-file reasoning to stronger cloud models. Routing should be measured and configurable, not a fixed subagent model alias or message-count cutoff.

## Target architecture

1. **CLI/application shell:** terminal-first interactive UI plus headless/JSON/RPC mode and an embeddable SDK.
2. **Agent runtime:** explicit event-driven loop with turn states, cancellation, retries, tool budgets, compaction and resumability.
3. **Provider/model layer:** common request/response/stream contract with capability metadata; adapters for Anthropic Messages, OpenAI Responses/Chat Completions, OpenRouter, llama.cpp, Ollama and compatible local endpoints.
4. **Routing policy engine:** task classification + capability fit + latency/cost/privacy constraints + model availability. Expose explainable routing decisions and manual override. Keep exploration local when feasible; escalate on uncertainty/errors/budget policy.
5. **Tool runtime:** typed JSON schemas, registry, read/glob/grep/edit/write/bash/git/test tools, output size limits, timeouts, working-directory confinement and deterministic error mapping.
6. **Permission/sandbox layer:** deny/ask/allow policy with project and tool scope, human approval for mutation and shell commands, allowlisted safe operations, environment/file secret protection, OS sandbox/container option and complete audit trail.
7. **Workspace layer:** canonical workspace root, symlink-aware path checks, git status/diff, checkpoints, worktrees and rollback.
8. **Session/context layer:** SQLite-backed sessions and event log, prompt/context budgets, output pruning, summary checkpoints and export/import.
9. **Extension layer:** versioned tools, hooks, subagents, skills (SKILL.md), MCP client, templates and themes. Extensions never bypass permissions.
10. **Commercial control plane (later):** organization policy, identity/SSO, billing, quotas, managed credentials, audit, telemetry opt-in and fleet configuration. Keep local execution functional without cloud control plane.

## EARS requirements plan

EARS patterns used: **Ubiquitous** (The system shall...), **Event-driven** (When...), **State-driven** (While...), **Unwanted behavior** (If...), and **Optional feature** (Where...). Each requirement has a stable ID and measurable acceptance criteria.

### Phase 0 — Safety and reliability foundation (P0)

- **REQ-001 — Default-safe execution (Ubiquitous):** The system shall require explicit user approval before executing shell commands or mutating workspace files unless a narrowly scoped allow rule exists.  
  *Acceptance:* default policy denies or asks for bash/write/edit; read-only tools can be separately allowed; no shipped workflow uses a dangerous permission bypass.
- **REQ-002 — Workspace confinement (Ubiquitous):** The system shall constrain file tools to the configured workspace and reject traversal and symlink escapes.  
  *Acceptance:* tests cover absolute paths, `..`, symlink escapes, nonexistent paths and path normalization.
- **REQ-003 — Typed tool calls (Event-driven):** When the model emits a tool call, the system shall validate tool name and arguments against the registered JSON schema before execution.  
  *Acceptance:* malformed JSON, unknown tools, missing/extra invalid fields and wrong types return typed errors and never invoke the tool.
- **REQ-004 — Protocol fidelity (Ubiquitous):** The provider layer shall preserve supported message roles, tool-use/result IDs, structured content, stop reasons and usage metadata across provider adapters.  
  *Acceptance:* fixture-based round-trip tests for text, multiple tool calls, tool results, images/unsupported blocks and errors.
- **REQ-005 — Honest streaming (Event-driven):** When streaming is requested, the system shall forward provider events incrementally or explicitly report that the adapter is non-streaming.  
  *Acceptance:* event sequence matches documented protocol, partial tool JSON is accumulated safely, no synthetic zero-usage completed-response stream is presented as live generation.
- **REQ-006 — Bounded service (Ubiquitous):** The local API shall enforce maximum request size, concurrency, queue wait, provider timeout and output size.  
  *Acceptance:* over-limit and overload requests return stable 4xx/429 errors; a stalled request does not block health/readiness endpoints or other requests.
- **REQ-007 — Safe secrets (Ubiquitous):** The system shall load provider credentials from environment or OS secret storage and shall not serialize plaintext secrets into generated project files or logs.  
  *Acceptance:* tests assert settings output contains no API key; log redaction tests cover key-shaped strings.
- **REQ-008 — Safe failure and fallback (Event-driven):** If a local provider fails, times out, or reports context exhaustion, the router shall apply configured retry/escalation rules without duplicating side-effecting tool execution.  
  *Acceptance:* deterministic fault-injection tests for timeout, 429, 5xx, invalid response, context overflow and unavailable provider.
- **REQ-009 — Configuration validation (Event-driven):** When the process starts, the system shall validate model/provider URLs, timeouts, budgets and policy configuration before accepting requests.  
  *Acceptance:* invalid config fails fast with actionable, redacted error messages.
- **REQ-010 — Regression test baseline (Ubiquitous):** The repository shall provide an automated test suite and CI for supported Python versions.  
  *Acceptance:* unit tests cover conversion, parsing, routing and scripts; CI runs lint, type checks and tests on pull requests.

### Phase 1 — Independent agent runtime (P1)

- **REQ-011 — Agent loop (Ubiquitous):** The runtime shall orchestrate model responses, tool execution and follow-up turns without depending on Claude Code.  
  *Acceptance:* headless task can read/search/edit a fixture repo, run tests under approval, and produce a final response.
- **REQ-012 — Provider abstraction (Ubiquitous):** The runtime shall support provider adapters behind a stable typed interface and select models by declared capabilities.  
  *Acceptance:* adapter contract tests run against mocked Anthropic/OpenAI/local-compatible providers.
- **REQ-013 — Session persistence (Event-driven):** When a session event occurs, the runtime shall append it to a durable session store and recover unfinished sessions after restart.  
  *Acceptance:* restart/resume integration tests preserve message/tool ordering and metadata.
- **REQ-014 — Context budget (State-driven):** While a conversation approaches the selected model's context budget, the runtime shall prune redundant tool output or create a summary checkpoint before overflow.  
  *Acceptance:* deterministic tests preserve recent user intent, relevant decisions and tool provenance.
- **REQ-015 — Routing policy (Event-driven):** When a task is classified, the router shall select a local or cloud model using capability, privacy, latency, cost and availability policy.  
  *Acceptance:* decision record includes selected provider, reason, fallback and budget; user can override route.
- **REQ-016 — CLI experience (Ubiquitous):** The product shall expose interactive, print and machine-readable modes with consistent behavior.  
  *Acceptance:* CLI supports project path, provider/model selection, permissions, JSON events and non-interactive execution.
- **REQ-017 — Workspace recovery (Event-driven):** When a mutating operation is approved, the runtime shall create a recoverable checkpoint and show a diff before finalization.  
  *Acceptance:* undo restores prior contents for supported operations; tests cover rollback failure.
- **REQ-018 — Session observability (Ubiquitous):** The runtime shall expose structured logs and per-turn token, latency, tool and estimated-cost metrics with sensitive values redacted.  
  *Acceptance:* metrics are testable without external services and can be disabled.

### Phase 2 — Extensibility and scale (P1/P2)

- **REQ-019 — Tool and agent extensions (Where configured):** Where an extension is enabled, the runtime shall discover and load its versioned tools/agents under the same policy enforcement as built-ins.  
  *Acceptance:* bad/unsupported extensions fail isolated; extension cannot grant itself additional permissions.
- **REQ-020 — MCP integration (Where configured):** Where an MCP server is configured, the runtime shall discover tools with timeouts, bounded schemas and explicit per-server permissions.  
  *Acceptance:* server failure does not crash core session; permission prompts include server/tool identity.
- **REQ-021 — Subagents (Where enabled):** Where subagents are enabled, the parent shall delegate bounded tasks with separate model, context and permission budgets.  
  *Acceptance:* maximum depth/concurrency enforced; child cannot exceed parent workspace or permission scope.
- **REQ-022 — Parallel sessions (Event-driven):** When multiple sessions operate on one repository, the system shall isolate concurrent edits using separate worktrees or explicit conflict detection.  
  *Acceptance:* integration tests show independent branches/worktrees and clear conflict reporting.
- **REQ-023 — Cross-platform distribution (Ubiquitous):** The product shall provide reproducible installation and updates on Linux, macOS and Windows.  
  *Acceptance:* CI builds/test packages on supported OSs; signed artifacts and SBOM are published.

### Phase 3 — Commercial readiness (P2)

- **REQ-024 — Team policy (Where managed workspace enabled):** Where a managed workspace is enabled, administrators shall define model allowlists, data boundaries, tool permissions and retention policy.  
  *Acceptance:* policy is enforced locally and has a documented offline behavior.
- **REQ-025 — Usage accounting (Event-driven):** When a provider request completes, the system shall meter provider, model, tokens, latency and cost estimate against user/team quotas.  
  *Acceptance:* idempotent usage records and budget exhaustion tests; transparent estimates.
- **REQ-026 — Enterprise identity/audit (Where enterprise tier enabled):** Where enterprise features are enabled, the service shall support SSO, role-based access, audit export and configurable retention.  
  *Acceptance:* threat-model review and integration tests before GA.
- **REQ-027 — Privacy controls (Ubiquitous):** The product shall document and enforce which source files, prompts, tool outputs and telemetry leave the device for each route.  
  *Acceptance:* local-only mode has network-egress tests; cloud routing clearly identifies transmitted context.
- **REQ-028 — Release governance (Ubiquitous):** The project shall publish supported-version policy, dependency inventory, vulnerability reporting route and signed release artifacts.  
  *Acceptance:* release pipeline emits SBOM, checksum/signature and provenance metadata.

## Prioritization and delivery sequence

| Order | Deliverable | Scope | Exit gate |
|---|---|---|---|
| 1 | Secure baseline | safe defaults, path safety, schema validation, secret handling, bounded HTTP, tests | no unsafe bypass; core tests + CI green |
| 2 | Runtime core | provider interface, tool registry, agent loop, events | end-to-end local/mock coding task |
| 3 | Developer UX | CLI modes, sessions, diff/undo, context compaction | resumable interactive task with safe mutation |
| 4 | Hybrid intelligence | router, local specialist, cloud escalation, evals | reproducible cost/quality/latency tradeoff |
| 5 | Extensions and concurrency | MCP, skills, subagents, worktrees | bounded and permission-safe concurrent task |
| 6 | Commercial operations | identity, quotas, managed policy, audit, packaging | security review + operational readiness |

## Optimization recommendations

- **Do not call a small model for every tool turn by default.** Use local models for high-volume, low-risk retrieval/classification and compact summaries. Escalate when confidence is low, tool selection fails validation, the task needs edits, or the cloud model has better capability.
- **Route by expected value, not message count.** Define task classes (repo map, symbol lookup, code explanation, design, edit, debugging, review) and track local success rate, latency, cost and escalation rate per class.
- **Keep local model prompts compact and retrieval grounded.** Use ripgrep/glob/AST/LSP/indexing before generation; return bounded excerpts with file/line provenance, not entire files.
- **Implement output caps and context budgets.** Summarize large tool results, deduplicate overlapping snippets, prune stale outputs and persist summaries.
- **Use concurrency deliberately.** Parallelize independent read-only searches; serialize conflicting writes and cap local GPU inference concurrency based on memory.
- **Instrument every decision.** Track route, reason, tokens, queue time, model latency, retries, context overflow, tool call validity, approval latency and task outcome.
- **Benchmark real repository outcomes.** Add SWE-bench-like issue tasks, repo-specific tasks, edit/test loops, ground-truth assertions, blind model comparisons and cost/latency distributions. A 65-item teacher-labeled tool-choice set alone is not a commercial KPI.
- **Separate developer and control planes.** Local CLI must continue working offline; hosted services should add team governance, collaboration and billing rather than being required for core coding.
- **Adopt a narrow, typed core.** Keep tools and agent extensions pluggable; avoid coupling runtime to an individual model, API dialect, UI or one CLI vendor.
- **Treat prompt injection as untrusted input.** Repository files, web results, tool outputs and MCP content are data, never authority to override system policy. Apply least privilege and human approval for high-impact operations.

## First implementation slice in this PR

The current change is intentionally a foundation, not an attempt to build the entire commercial platform in one patch:

1. Add automated unit tests for local-response parsing and protocol behavior.
2. Replace silent malformed tool-call dropping with typed/visible failure behavior and validate tool-call envelope shape.
3. Bound incoming HTTP request size and normalize client-visible errors.
4. Remove dangerous permission bypass flags from example execution paths; replace with explicit opt-in requirements.
5. Stop embedding provider credentials in generated settings; document runtime environment loading.
6. Add CI and development test configuration.

**Not yet solved by this slice:** full provider abstraction, true streaming, safe shell sandbox, permission UX, local-first agent loop, session store, context compaction, durable diff/undo, multi-user control plane and enterprise features. Those require separate architectural increments and deeper test coverage.

## Review and validation notes

This document and the accompanying foundation changes should be treated as a first engineering review. Before a production release, run the test suite in an isolated environment with a real local inference server, validate provider terms/model licensing, conduct threat modeling and perform an independent security review.
