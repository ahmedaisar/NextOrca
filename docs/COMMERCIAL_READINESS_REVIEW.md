# Commercial Readiness Review and EARS Plan

**Repository:** https://github.com/ahmedaisar/NextOrca  
**Baseline:** `main` @ `e0d2c37bd4dbbd61368b533b6b202a488ff29160`  
**Review date:** 2026-11-08  
**Scope:** current tracked source, CLI/runtime, provider and routing layers, workspace tools, sessions, MCP sandbox, legacy proxy/scripts, tests, CI, evaluation corpus, packaging and public documentation.  
**Method:** source and test inspection plus the repository CI workflow. This is not a penetration test, model-quality study, performance benchmark, or external-provider integration test.

## Executive assessment

NextOrca has moved materially beyond the earlier proxy-and-batch-analysis prototype. The current `main` branch contains an independent Python agent loop, a typed provider contract, an OpenAI Chat Completions-compatible adapter, deterministic local/cloud routing, workspace-scoped tools, default read-only permissions, opt-in diff-approved file mutations, SQLite sessions and checkpoints, local usage metrics, and an experimental Linux Bubblewrap-backed MCP stdio integration.

**Recommendation: continue as an experimental developer tool; do not represent the current build as commercially hardened or enterprise-ready.** The independent runtime is now a real product foundation, but it is still narrow: one provider protocol family, no general shell tool, no interactive terminal UI, deterministic routing rather than measured capability selection, limited context management, and no operational control plane. The MCP integration increases extensibility but also introduces a meaningful host-security boundary that must be independently reviewed.

The previous review's statement that Claude Code supplied most of the agent loop is no longer accurate for the current default CLI runtime. The legacy proxy and Claude-oriented helper scripts remain in the repository as a separate compatibility path; they should not be confused with the standalone `nextorca` runtime.

## Baseline inventory

### Independent runtime (`nextorca/`)

- `cli.py`: headless prompt CLI; single-provider and hybrid modes; local-only privacy mode; opt-in edits and MCP; session, checkpoint and metrics commands.
- `runtime.py`: provider-independent model/tool loop, bounded turn/tool counts and tool output, permission-policy enforcement, events and session integration.
- `provider.py`, `openai_compatible.py`, `types.py`: normalized provider contract and OpenAI Chat Completions-compatible request/response adapter.
- `tool_registry.py`: named tool registry, provider tool descriptions, argument validation and prepared operations.
- `workspace.py`: workspace-rooted Read/Glob/Grep tools and opt-in Write/Edit operations, bounded file/search output, diff previews and checkpoint-aware mutations.
- `permissions.py`: automatic read-only access and explicit interactive approval for mutations with a reviewable preview.
- `routing.py`: deterministic task classification and local/cloud selection, including explicit route modes and local-only privacy behavior.
- `context.py`: bounded conversation context with preservation of recent messages.
- `session_store.py`: SQLite-backed session/message/checkpoint and provider-metric persistence.
- `mcp_stdio.py`, `sandbox.py`: experimental MCP stdio discovery/calls, schema registration, process lifecycle and Linux Bubblewrap isolation.

### Compatibility and supporting code

- `scripts/proxy.py`, `scripts/agent_protocol.py`, `scripts/proxy_security.py`: retained Anthropic-shaped proxy path, read-only local-model tool-call parsing, request/authentication validation and protocol conversion.
- `scripts/setup.sh`, `scripts/generate_claude_settings.py`, `scripts/start_services.sh`, `scripts/analyze.sh`, `scripts/test_single.sh`: legacy Claude-oriented setup, service and analysis helpers.
- `evals/evaluate_routing.py`, `evals/routing_cases.json`: deterministic classifier evaluation corpus and thresholded evaluator.
- `tests/`: unit tests for agent protocol/runtime, context, routing, MCP, sandbox, provider adapter, proxy/setup security, workspace mutations, sessions and metrics.
- `.github/workflows/ci.yml`: Ubuntu/Python 3.12 CI; installs Bubblewrap/AppArmor, installs dev dependencies, checks package metadata, Ruff, Python compilation, shell syntax, CLI help, routing evaluation and pytest.
- `pyproject.toml`: Python 3.12+, setuptools package, `nextorca` console entry point, runtime dependencies and optional pytest/Ruff development dependencies.

## Current capabilities and boundaries

### Implemented and covered by repository tests

1. Independent tool-using agent loop with normalized assistant/tool-call types.
2. OpenAI Chat Completions-compatible provider adapter; local and hosted endpoints use the same interface.
3. Built-in Read, Glob and Grep tools, with workspace path resolution and output/file-count limits.
4. Default read-only execution; Write/Edit tools are opt-in and require interactive approval of a generated diff.
5. SQLite-backed sessions and checkpoint metadata, including session resume and guarded undo.
6. Deterministic hybrid routing, manual local/cloud selection, and a local-only privacy mode.
7. Local provider/latency/token/routing metrics; no analytics service is required.
8. Explicitly configured MCP stdio servers, with tool schema checks, per-call approval, bounded manifests, process timeouts and fail-closed Linux Bubblewrap setup.
9. Regression checks for path traversal/symlink escape, invalid tool arguments, permission denial, session behavior, MCP process cleanup, sandbox policy and protocol parsing.

### Important boundaries

- The built-in runtime does not expose general-purpose shell execution. It is not yet a drop-in replacement for a full terminal coding agent.
- The provider contract is narrow and the concrete adapter is OpenAI Chat Completions-compatible. Native Anthropic Messages, OpenAI Responses, streaming, images and richer multimodal/tool semantics are not implemented as first-class adapters.
- The router uses a deterministic prompt classifier. Its evaluation measures agreement with a checked-in label corpus, not task success, model competence, confidence calibration, cost savings or end-to-end coding quality.
- Context management is bounded/pruning-oriented; it is not a complete semantic compaction and long-horizon memory system.
- File undo is checkpoint-aware and refuses to overwrite changed targets, but it is not a general git transaction or repository-wide rollback mechanism.
- MCP is experimental and Linux-only. Bubblewrap is required; writable-path grants permit direct server writes outside the NextOrca diff/undo path, and explicit network grants weaken the default network-isolation posture. Bubblewrap is not a VM and the current sandbox does not provide comprehensive CPU, memory or process quotas.
- The legacy proxy remains a separate compatibility path with different protocol and security characteristics. Do not assume the standalone runtime's guarantees automatically apply to it.
- No production deployment, real-model integration, provider interoperability matrix, independent security audit, threat-model sign-off or commercial support operation is established by the repository tests.

## Updated risk assessment

### P0 — must close before a commercial security claim

- **MCP host boundary:** Bubblewrap, seccomp/network behavior, executable/path mapping, environment allowlisting, writable mounts, process teardown and host-kernel assumptions need independent security review and adversarial testing. A writable MCP grant is a direct capability, not a reviewed NextOrca file edit.
- **Workspace mutation race resistance:** path confinement and atomic writes are present, but the file-system boundary should be reviewed for time-of-check/time-of-use races, hard links, mount behavior, permission preservation and concurrent writers before treating it as a hardened sandbox.
- **Legacy proxy posture:** proxy authentication and request-size validation exist, but the full HTTP server still needs a threat-model review for concurrency/queue bounds, timeouts, cancellation, error redaction, request lifecycle and protocol fidelity. The legacy path must not inherit the new runtime's safety claims by association.
- **Provider response and retry safety:** the provider adapter needs contract tests against real compatible implementations, malformed/oversized responses, timeout/429/5xx behavior and retry semantics. Fallback must not duplicate any future side effects.
- **Secret lifecycle:** environment-based credentials are preferable to generated plaintext settings, but a complete credential lifecycle, redaction coverage, crash/log review and cloud data-flow documentation are still needed.
- **Approval boundary:** interactive approvals are appropriate for the current local CLI, but non-interactive/headless use needs a deliberate policy that cannot silently convert ask into allow.

### P1 — independent runtime and reliability gaps

- No native provider adapters for Anthropic Messages or OpenAI Responses; no first-class streaming or multimodal contract.
- No interactive TUI, SDK/RPC contract, cancellation, resumable in-flight operation or structured event protocol suitable for external clients.
- No semantic context compaction, explicit context provenance or configurable per-model context/token budgets.
- Routing is deterministic and corpus-scored; it does not use measured capability, privacy labels per tool datum, latency, cost, health or calibrated confidence.
- Session persistence is local SQLite without a documented migration/versioning policy, encryption-at-rest option, retention controls or multi-process concurrency guarantees.
- No git worktree isolation, repository checkpoint, conflict detection or concurrent-session isolation.
- No extension compatibility/version policy, skills framework or bounded subagent runtime.
- Automated tests are valuable regression coverage but do not prove real-model task success, provider compatibility, reliability under load or security against a malicious MCP server.
- Python support/CI is currently centered on Python 3.12 and Ubuntu; cross-platform installation and sandbox support are incomplete.

### P2 — commercial operations and enterprise readiness

No organization/user identity, SSO/SCIM, RBAC, managed policy distribution, billing, quotas, cost allocation, central audit export, retention administration, support SLA, vulnerability disclosure process, signed releases, SBOM/provenance, release channel or privacy-safe product analytics.

## Competitive architecture implications

### OpenCode

Its broad client, provider, plugin, MCP, agent and permission surface demonstrates that session management, policy and extension safety are core product architecture, not optional model features. NextOrca should not attempt feature parity before its own runtime and safety boundaries are proven.

### Pi

Its small, composable model/provider, agent-loop and tool-execution layers are a useful reference. NextOrca's provider contract and registry are a reasonable start; keep the core typed and narrow, and prevent extensions from bypassing policy.

### NextOrca differentiation

The most credible wedge remains **local-first code intelligence with transparent hybrid inference**: local retrieval, repository mapping and bounded explanation, with optional cloud escalation for tasks that warrant it. The differentiation must be demonstrated with reproducible task-success, latency, privacy and cost measurements—not just classifier accuracy.

## EARS requirements and current disposition

Status meanings: **Implemented** = present in current code with relevant automated tests; **Partial** = a limited implementation exists but acceptance criteria are not fully met; **Open** = not implemented or not demonstrated by repository evidence. Status describes the current repository, not a commercial certification.

### Phase 0 — safety and reliability (P0)

- **REQ-001 — Safe execution (Ubiquitous): Partial.** Default policy allows registered read-only tools; mutations are opt-in and require interactive diff approval. No built-in Bash tool exists. A general headless approval policy and policy allowlists are not implemented.
- **REQ-002 — Workspace confinement (Ubiquitous): Partial.** Workspace path normalization, traversal checks, symlink-escape checks and tests exist. Hardened race-resistant confinement across all filesystem edge cases is not independently established.
- **REQ-003 — Typed tool calls (Event-driven): Partial.** Registered tool names and a bounded JSON Schema subset are validated; unknown arguments/types are rejected. This is not a complete JSON Schema implementation and the legacy proxy has its own separate parser.
- **REQ-004 — Protocol fidelity (Ubiquitous): Partial.** A normalized internal turn contract and OpenAI Chat Completions adapter exist. Full cross-provider round trips, streaming, multimodal content and richer protocol semantics remain open.
- **REQ-005 — Honest streaming (Event-driven): Open.** The standalone provider contract is request/response and does not provide incremental streaming.
- **REQ-006 — Bounded service (Ubiquitous): Partial.** Tool outputs, file/search sizes, MCP manifests and MCP request timeouts are bounded. Comprehensive API request/concurrency/queue/output limits and service overload behavior are not established across all paths.
- **REQ-007 — Secret hygiene (Ubiquitous): Partial.** Provider keys are accepted through environment/CLI configuration and MCP child environments are allowlisted. End-to-end secret redaction, secure credential storage and full log/crash auditing remain open.
- **REQ-008 — Safe fallback (Event-driven): Partial.** Hybrid local/cloud routing and provider availability handling exist. A comprehensive fault-injection matrix and proof against duplicate side effects are not established.
- **REQ-009 — Validated configuration (Event-driven): Partial.** CLI choices and MCP manifest fields are validated. Uniform startup validation for all URLs, model settings, budgets, policies and deployment modes remains incomplete.
- **REQ-010 — CI and regression baseline (Ubiquitous): Implemented.** CI installs Python 3.12/dev dependencies, runs Ruff, compilation, shell syntax, package-version and CLI checks, routing evaluation and pytest. It is a single Ubuntu/Python lane, not a broad platform/version matrix.

### Phase 1 — independent coding runtime (P1)

- **REQ-011 — Agent loop (Ubiquitous): Implemented.** The standalone runtime coordinates provider turns, validated tool calls, permission checks, bounded tool output and final responses; fake-provider tests cover the loop.
- **REQ-012 — Provider abstraction (Ubiquitous): Partial.** A provider protocol and OpenAI-compatible adapter exist. Multiple native provider families and capability discovery are not implemented.
- **REQ-013 — Durable sessions (Event-driven): Partial.** SQLite persists messages and session/checkpoint metadata, and resume behavior is tested. Migration policy, crash recovery guarantees and multi-process contention behavior need more work.
- **REQ-014 — Context budget (State-driven): Partial.** A bounded context manager prunes older messages while preserving recent turns. Semantic summaries, provenance retention and model-token-aware budgeting remain open.
- **REQ-015 — Hybrid routing (Event-driven): Partial.** Local/cloud route modes, deterministic classification and local-only mode exist. Capability/latency/cost/health-aware routing and route-quality outcome measurement remain open.
- **REQ-016 — CLI modes (Ubiquitous): Partial.** A headless prompt CLI and structured stderr events exist. An interactive terminal UI, stable JSON/RPC interface and SDK are not present.
- **REQ-017 — Workspace recovery (Event-driven): Partial.** Approved edits produce diffs/checkpoints and guarded undo. Git checkpoints, multi-file transactions and robust concurrent mutation recovery are not present.
- **REQ-018 — Observability (Ubiquitous): Partial.** Local provider, latency, token and routing metrics are persisted and summarized. Cost estimates, trace correlation, export and comprehensive privacy controls are not implemented.

### Phase 2 — extensibility and scale (P1/P2)

- **REQ-019 — Extensions (Where enabled): Partial.** MCP stdio servers can register tools under the existing permission policy. A versioned general extension API, compatibility lifecycle and isolation for arbitrary extension types are not present.
- **REQ-020 — MCP (Where configured): Partial.** Discovery, legacy/modern handshake handling, tool-schema checks, per-call approval, timeouts and Linux Bubblewrap isolation exist. Cross-platform sandboxing, comprehensive resource quotas and independent security validation remain open.
- **REQ-021 — Subagents (Where enabled): Open.** No bounded child-agent runtime or parent/child permission inheritance is implemented.
- **REQ-022 — Parallel sessions (Event-driven): Open.** No worktree isolation or explicit concurrent-edit conflict model is implemented.
- **REQ-023 — Cross-platform distribution (Ubiquitous): Partial.** The project is installable as a Python package from source. Reproducible Windows/macOS/Linux packaging, sandbox backends and OS CI coverage are not complete.

### Phase 3 — commercial operations (P2)

- **REQ-024 — Admin policy (Where managed workspace enabled): Open.** No managed organization/workspace policy service exists.
- **REQ-025 — Metering and quotas (Event-driven): Open.** Local token/latency metrics exist, but billing-grade metering, cost accounting and quota enforcement do not.
- **REQ-026 — Enterprise identity/audit (Where enterprise tier enabled): Open.** No SSO, SCIM, RBAC or central audit export exists.
- **REQ-027 — Privacy routing (Ubiquitous): Partial.** Local-only routing mode prevents selection of the cloud provider in the standalone runtime. End-to-end network-egress tests, data classification and user-visible per-route disclosure are not comprehensive.
- **REQ-028 — Release governance (Ubiquitous): Open.** The repository includes an MIT license and CI, but no evidenced signed release, SBOM, provenance attestation, support policy or vulnerability response process.

## Validation against the current baseline

### Repository CI contract

The current `.github/workflows/ci.yml` defines one Ubuntu job that:

1. Installs Python 3.12 and the Linux Bubblewrap/AppArmor prerequisites.
2. Installs the package and development dependencies with `uv sync --extra dev`.
3. Asserts the installed distribution version is `0.8.0`.
4. Runs Ruff over the selected legacy proxy modules, the `nextorca` package, tests and evaluations.
5. Compiles proxy modules and all `nextorca/*.py` modules.
6. Runs `bash -n` against the four retained shell scripts.
7. Runs `nextorca --help`.
8. Runs the routing corpus with a 95% minimum accuracy threshold.
9. Runs the pytest suite, including real Bubblewrap-dependent checks on the configured Linux runner.

The workflow does not run live local-model or hosted-provider calls, a multi-OS/Python matrix, performance/load tests, static type checking, dependency vulnerability scanning, or an external penetration test. A passing workflow is a regression baseline, not a commercial-readiness certification.

### Local reproduction commands

Run from the repository root with Python 3.12, `uv`, and (for MCP sandbox tests) Linux Bubblewrap available:

```bash
uv sync --extra dev
uv run python -c "from importlib.metadata import version; assert version('nextorca') == '0.8.0'"
uv run ruff check scripts/agent_protocol.py scripts/generate_claude_settings.py scripts/proxy_security.py nextorca tests evals
uv run python -m py_compile scripts/proxy.py scripts/proxy_security.py nextorca/*.py
for script in scripts/setup.sh scripts/analyze.sh scripts/test_single.sh scripts/start_services.sh; do bash -n "$script"; done
uv run nextorca --help
uv run python evals/evaluate_routing.py --fail-under 0.95
uv run pytest
```

### Evidence interpretation

- Unit tests use fake providers and fixture workspaces for much of the standalone runtime; they validate deterministic contracts but do not establish behavior with arbitrary real models.
- MCP tests require Linux and Bubblewrap. Ubuntu 24.04+ may require a Bubblewrap-scoped AppArmor user-namespace profile; do not disable the global user-namespace restriction as a workaround.
- Routing accuracy is measured against a small, repository-maintained set of hand-labeled prompts. It is a classifier regression metric only.
- Real llama.cpp/OpenRouter/provider interoperability, model licensing, threat modeling, load/performance, data-retention review and independent security review remain separate validation work.

## Prioritized delivery

1. **Security assurance:** independently review workspace mutation races, MCP Bubblewrap/seccomp and writable mounts, legacy proxy, credentials, logging and headless approval policy.
2. **Runtime contracts:** add provider contract tests and adapters for the protocols actually targeted; define streaming, cancellation, structured errors and retry/idempotency semantics.
3. **Developer workflow:** add an interactive terminal experience, stable JSON/RPC/SDK interface, git-aware checkpoints and conflict-safe workspace isolation.
4. **Hybrid quality:** benchmark end-to-end repository tasks against local-only/cloud-only baselines; report task success, latency, tokens, estimated cost, privacy route and escalation rates.
5. **Context and extensibility:** add token-aware semantic compaction, versioned extension contracts, bounded subagents and parent-scoped permissions.
6. **Commercial operations:** only after the local runtime is secure and useful, add identity, managed policy, quotas, audit export, retention, signed releases, SBOM/provenance and support processes.

## Optimization recommendations

- Keep retrieval deterministic and local where possible: indexed search, globbing, AST/LSP and bounded line-numbered context should precede generation.
- Route by measured task outcomes and explicit privacy/capability constraints, not prompt keywords alone; preserve user overrides and explain each decision.
- Do not use routing-corpus accuracy as a proxy for coding-agent quality. Build repository issue/edit/test tasks with independent assertions and blinded comparisons.
- Make all execution modes share one permission policy. Headless operation should fail closed when approval cannot be obtained.
- Treat repository content, provider responses and MCP descriptions/results as untrusted data; they must never change policy or permissions.
- Keep MCP network access and writable mounts disabled unless a specific server requires them; document each granted capability and its effect on the review/undo boundary.
- Instrument request IDs, provider/model, route reason, token usage, latency, tool calls, approval decisions, errors and task outcomes locally, with explicit redaction and opt-out behavior.
- Keep the standalone local runtime useful without a hosted control plane; hosted features should add governance and collaboration rather than gate core execution.

## Review conclusion

The current repository is a substantially more capable experimental coding-agent runtime than the earlier baseline. It has meaningful safety-oriented foundations and a growing regression suite, but those foundations are not equivalent to a hardened execution sandbox or commercial assurance. The immediate go/no-go boundary is independent security validation of the MCP and filesystem boundaries, followed by real-provider contract testing and task-level evaluation. Commercial packaging, enterprise controls and a public production-readiness claim should remain deferred until those gates are met.
