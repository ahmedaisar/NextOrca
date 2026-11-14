# Plan 007: Provider adapter registry and four selected provider integrations

> **Executor instructions**: First inspect current provider and router contracts. This plan extends supported model transports without changing the agent loop. The maintainer selected four targets on 2026-11-14: Anthropic Messages API, Claude Code CLI, OpenAI Codex CLI, and Gemini API. Implement them as four focused PRs, not one large change. Never claim tool/stream compatibility that the transport does not provide. CLI adapters must preserve NextOrca permission checks and tool execution boundaries; do not delegate workspace access to a provider CLI behind the runtime.

> **Drift check (run first)**: `git diff --stat 26b601c..HEAD -- nextorca/provider.py nextorca/openai_compatible.py nextorca/routing.py nextorca/cli.py nextorca/types.py nextorca/provider_registry.py pyproject.toml tests`. The registry/factory work is already merged at the current main baseline; compare live files before editing if they change again.

## Status

- **Execution state**: IN PROGRESS; Anthropic PR #43, Claude Code CLI PR #44, Codex CLI PR #45 and Gemini API PR #46 are in progress.
- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/006-session-discovery-and-resume.md and plans/005-full-screen-terminal-ui.md
- **Category**: direction
- **Planned at**: commit `f7ba50e`, 2026-11-12

## Why this matters

NextOrca already has a clean `ChatProvider` protocol and optional streaming protocol, but the CLI currently wires only `OpenAICompatibleProvider` for single-provider and hybrid local/cloud turns. Atomic Agent supports several native provider protocols and subscription-backed CLIs; that flexibility is valuable, but copying its entire provider catalogue would increase maintenance and support burden. Add an explicit provider construction/configuration seam and the four adapters explicitly selected by the maintainer: Anthropic Messages API, Claude Code CLI, OpenAI Codex CLI, and Gemini API. Keep each transport in its own focused pull request; native APIs and subscription-backed CLIs must preserve their distinct authentication, process and tool-execution boundaries.

## Current state

- `nextorca/provider.py` defines `ChatProvider.complete(model, messages, tools)` and `StreamingChatProvider.stream_complete(...)`.
- `nextorca/openai_compatible.py` implements the provider protocol using HTTPX and the Chat Completions-compatible `/chat/completions` endpoint. It normalises responses to `AssistantTurn` / `ProviderStreamChunk`.
- `nextorca/cli.py` now calls `build_runtime_provider(RuntimeProviderConfig(...))`; provider construction is implemented in `nextorca/provider_registry.py`. CLI transport IDs are configurable separately for single, local and cloud endpoints.
- `nextorca/routing.py` accepts provider instances through `HybridRouter`; the routing policy should stay independent from transport-specific request formats.
- `pyproject.toml` has `httpx` as the only runtime dependency; a native provider adapter can likely use HTTPX without adding another SDK.
- Tests already exercise provider transport and routing separately: `tests/test_openai_compatible.py`, `tests/test_hybrid_routing.py`, `tests/test_hybrid_streaming.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Provider tests | `uv run pytest tests/test_openai_compatible.py tests/test_hybrid_routing.py tests/test_hybrid_streaming.py -q` | Existing provider and routing tests pass |
| Full tests | `uv run pytest` | Exit 0 |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |
| CLI smoke | `uv run nextorca --help` | Exit 0 |

## Scope

**In scope**
- `nextorca/provider.py` — stable provider construction/transport contract if needed.
- `nextorca/provider_registry.py` — explicit adapter registry and runtime provider factory.
- `nextorca/cli.py` — provider selection/configuration only.
- Four focused transport adapters and their tests, delivered in separate PRs: Anthropic Messages API, Claude Code CLI, OpenAI Codex CLI and Gemini API.
- `tests/test_openai_compatible.py`, `tests/test_hybrid_routing.py` and new adapter/factory tests only where required.
- `README.md`, `docs/routing.md` and `docs/ROADMAP.md` to list supported protocols and limitations.

**Out of scope**
- Rewriting `AgentRuntime`, `HybridRouter`, session storage or tool schemas.
- Combining multiple provider transports into one implementation PR.
- Implementing CLI transports in a way that bypasses NextOrca tool permissions, approval gates, cancellation or process-lifecycle controls.
- Model marketplace, billing, cloud proxy service, API key vault or remote configuration sync.
- Changing local-only privacy guarantees or allowing silent provider fallback across privacy boundaries.

## Git workflow

- Branch: one focused feature branch per adapter, beginning with `feat/anthropic-messages-provider`.
- One PR per adapter. Use Conventional Commit messages such as `feat: add Anthropic Messages provider`.
- Keep CI limited to provider/routing tests plus normal quick PR checks.

## Steps

### Step 1: Extract provider construction from CLI

Introduce a small configuration-to-provider factory. It should support current single OpenAI-compatible and hybrid local/cloud construction with no behavioral change. The router continues to receive protocol instances and does not know provider-specific configuration fields.

**Verify**: `uv run pytest tests/test_openai_compatible.py tests/test_hybrid_routing.py tests/test_hybrid_streaming.py tests/test_cli_routing_defaults.py -q` → all existing cases pass unchanged.

### Step 2: Define the target-adapter compatibility checklist

`docs/provider-adapter-contract.md` records the normalized provider contract, currently registered adapters, and the compatibility checklist for the selected transports. Do not declare a new provider supported until its protocol and safety boundaries are validated against official API or CLI documentation.

**Verify**: the contract lists required tests for authentication, messages, tools, streaming, errors, usage, privacy/routing, lifecycle and terms, and accurately lists every registered adapter.

### Step 3: Implement the four selected adapters as separate PRs

1. Anthropic Messages API (native HTTP): normalize system/messages, tool schemas, tool-use blocks, usage and errors.
2. Claude Code CLI (subscription-backed): use schema-validated JSON output, disable built-in tools/MCP/session persistence, run outside the workspace, and return normalized tool proposals to NextOrca.
3. OpenAI Codex CLI (subscription-backed): use output-schema, disable workspace-capable features, run in a temporary directory with a read-only sandbox, and return structured tool proposals to NextOrca.
4. Gemini API (native HTTP): normalize system instructions, message/function-response history, function declarations, function calls, usage and provider errors.

Use HTTPX for native APIs and a bounded subprocess wrapper for CLI transports. Keep process cancellation and stderr/stdout separation explicit. A CLI that cannot safely satisfy `ChatProvider` must be exposed through a separate execution backend rather than falsely registered as a chat-completion adapter.

**Verify**: focused adapter tests pass with mocked HTTP responses or fake executable processes; no real API key or paid model call is required in CI.

### Step 4: Prove routing and privacy invariants

Run the same local/cloud and local-only behavior through the new adapter. Verify that local-only never invokes or falls back to cloud and that streaming cannot switch providers after partial output.

**Verify**: `uv run pytest tests/test_hybrid_routing.py tests/test_hybrid_streaming.py -q` → all tests pass, with additional cases for the new adapter.

## Test plan

- Factory preserves current single, local, cloud and auto configurations.
- Adapter parses regular text, tool calls, finish reason and token usage.
- Streaming handles partial chunks, final message, malformed frames, disconnect, timeout and cancellation.
- Error mapping distinguishes bad request/auth/schema errors from transient unavailability.
- Router policy and local-only privacy remain transport-agnostic and unchanged.
- Existing OpenAI-compatible provider behavior remains byte-for-byte compatible for current test fixtures.

## Done criteria

- [x] CLI no longer contains provider-construction duplication; current OpenAI-compatible setup remains default-compatible.
- [ ] Four selected integrations are complete: Anthropic Messages API, Claude Code CLI, OpenAI Codex CLI and Gemini API, each in a separate reviewed PR.
- [ ] Streaming/tool-call behavior is represented in adapter contract tests.
- [x] Local-only routing cannot reach cloud through the new registry/factory.
- [x] No provider-specific logic is placed in `AgentRuntime` or task classifier.
- [ ] Full pytest, Ruff and compileall pass.
- [x] Documentation lists only tested, supported capabilities.

## STOP conditions

Stop and report if:
- The selected API does not support the tool-call or streaming shape needed by the current protocol and adapting it would require a runtime redesign.
- A selected CLI integration cannot expose a safe, machine-readable tool-call boundary that preserves NextOrca approvals; stop and propose a separate execution-backend design rather than weakening the runtime.
- Supporting the adapter requires adding credentials to SQLite, command logs or prompt context.
- A permanent authentication/schema error would be treated as provider unavailability and silently trigger fallback.
- Implementing an adapter requires changing the public semantics of `ChatProvider` or `HybridRouter` without a separately reviewed protocol design.

## Maintenance notes

Keep provider-specific wire formats at the adapter boundary. The routing classifier should continue to make task decisions independently of provider format. Review secret handling, stream ordering, tool schema compatibility and cost/usage metadata before accepting the adapter.
