# Plan 007: Add a provider registry and one deliberately selected native adapter

> **Executor instructions**: First inspect current provider and router contracts. This plan is about extending supported model transports without changing the agent loop. Do not add multiple adapters at once or silently claim that all models from a provider are tool/stream compatible. Obtain a maintainer decision on the first target provider before implementing that adapter; if none is selected, complete only the provider registry/config design and report the decision needed.

> **Drift check (run first)**: `git diff --stat f7ba50e..HEAD -- nextorca/provider.py nextorca/openai_compatible.py nextorca/routing.py nextorca/cli.py nextorca/types.py nextorca/provider_registry.py pyproject.toml tests`. This execution is based on the TUI/session branch at `f7ba50e`. If any in-scope path changed after that baseline, compare the live provider construction and CLI tests before editing.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `f7ba50e`, 2026-11-12

## Why this matters

NextOrca already has a clean `ChatProvider` protocol and optional streaming protocol, but the CLI currently wires only `OpenAICompatibleProvider` for single-provider and hybrid local/cloud turns. Atomic Agent supports several native provider protocols and subscription-backed CLIs; that flexibility is valuable, but copying its entire provider catalogue would increase maintenance and support burden. Add an explicit provider construction/configuration seam and one adapter chosen from an actual maintainer use case.

## Current state

- `nextorca/provider.py` defines `ChatProvider.complete(model, messages, tools)` and `StreamingChatProvider.stream_complete(...)`.
- `nextorca/openai_compatible.py` implements the provider protocol using HTTPX and the Chat Completions-compatible `/chat/completions` endpoint. It normalises responses to `AssistantTurn` / `ProviderStreamChunk`.
- `nextorca/cli.py` now delegates construction to `nextorca/provider_registry.py`; the provider registry has an explicit `openai-compatible` adapter and a configuration-to-runtime factory. Adapter selection is configurable separately for single, local and cloud routes.
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
- `nextorca/provider_registry.py` — small adapter registry and runtime-provider factory.
- `nextorca/cli.py` — provider selection/configuration only.
- One native adapter module and focused tests, after target provider selection.
- `tests/test_openai_compatible.py`, `tests/test_hybrid_routing.py` and new adapter/factory tests only where required.
- `README.md`, `docs/routing.md` and `docs/ROADMAP.md` to list supported protocols and limitations.

**Out of scope**
- Rewriting `AgentRuntime`, `HybridRouter`, session storage or tool schemas.
- Adding more than one new provider adapter in this plan.
- Copying Atomic Agent's Claude/Codex subscription CLI adapters without confirming that the operator wants those CLIs and accepts their lifecycle/usage constraints.
- Model marketplace, billing, cloud proxy service, API key vault or remote configuration sync.
- Changing local-only privacy guarantees or allowing silent provider fallback across privacy boundaries.

## Git workflow

- Branch: `feat/provider-adapter-registry`.
- One focused PR. Use Conventional Commit messages such as `feat: add provider adapter registry`.
- Keep CI limited to provider/routing tests plus normal quick PR checks.

## Steps

### Step 1: Extract provider construction from CLI

Introduce a small configuration-to-provider factory. It should support current single OpenAI-compatible and hybrid local/cloud construction with no behavioral change. The router continues to receive protocol instances and does not know provider-specific configuration fields.

**Verify**: `uv run pytest tests/test_openai_compatible.py tests/test_hybrid_routing.py tests/test_hybrid_streaming.py tests/test_cli_routing_defaults.py -q` → all existing cases pass unchanged.

### Step 2: Define the target-adapter compatibility checklist

`docs/provider-adapter-contract.md` records the normalized contract, the single currently implemented adapter and the required checklist for the first native adapter. It deliberately does not declare an unselected provider supported. A target provider must be selected explicitly before its official endpoint/authentication/tool/stream/error semantics can be verified.

**Verify**: `docs/provider-adapter-contract.md` contains explicit acceptance questions and required tests for authentication, messages, tools, streaming, errors, usage, privacy/routing and lifecycle; it states that only `openai-compatible` is currently registered.

### Step 3: Implement only the selected adapter (blocked until target selection)

STOP this step until the maintainer selects a provider transport and explicitly clarifies whether it is a native HTTP API or a subscription CLI. Do not choose a target on their behalf. Once selected, use HTTPX unless a concrete requirement justifies another dependency. Normalize to the existing turn/chunk types. Preserve the existing error distinction between permanent protocol/request errors and availability errors; do not let the router fall back on arbitrary provider failures.

**Verify**: focused adapter tests pass with mocked HTTP responses and stream frames; no real API key or paid model call is required in CI.

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

- [ ] CLI no longer contains provider-construction duplication; current OpenAI-compatible setup remains default-compatible.
- [ ] One additional native adapter is implemented only after its target is explicitly selected (currently blocked; no target was selected during this execution).
- [ ] Streaming/tool-call behavior is represented in adapter contract tests.
- [ ] Local-only routing cannot reach cloud through the new adapter.
- [ ] No provider-specific logic is placed in `AgentRuntime` or task classifier.
- [ ] Full pytest, Ruff and compileall pass.
- [ ] Documentation lists only tested, supported capabilities.

## STOP conditions

Stop and report if:
- The selected API does not support the tool-call or streaming shape needed by the current protocol and adapting it would require a runtime redesign.
- Provider target is not selected by the maintainer; do not guess between Claude CLI, Codex CLI, Anthropic API or another provider.
- Supporting the adapter requires adding credentials to SQLite, command logs or prompt context.
- A permanent authentication/schema error would be treated as provider unavailability and silently trigger fallback.
- Implementing one adapter requires changing the public semantics of `ChatProvider` or `HybridRouter`.

## Maintenance notes

Keep provider-specific wire formats at the adapter boundary. The routing classifier should continue to make task decisions independently of provider format. Review secret handling, stream ordering, tool schema compatibility and cost/usage metadata before accepting the adapter.
