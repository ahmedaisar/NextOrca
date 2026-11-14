# Provider adapter contract

**Status:** active contract for the provider registry  
**Implemented adapters:** `openai-compatible`, `anthropic`  
**Owner:** `nextorca/provider.py`, `nextorca/provider_registry.py`

## Runtime boundary

The agent runtime consumes a `ChatProvider` implementation and an opaque model identifier. It does not make provider-specific HTTP requests, interpret vendor authentication, or know how a streaming response is framed.

The current normalized interface is:

- `ChatProvider.complete(model, messages, tools) -> AssistantTurn`
- Optional `StreamingChatProvider.stream_complete(model, messages, tools) -> Iterator[ProviderStreamChunk]`

A completed `AssistantTurn` carries text, ordered tool calls (with stable IDs and object arguments), finish reason and normalized token usage. A stream emits text deltas and ends with one final normalized turn. A provider that does not stream may implement only `complete`; `HybridRouter` wraps its response into one final stream chunk.

The registry factory uses `factory(base_url=..., api_key=...)`. Adapters with a provider-owned default endpoint may register with `requires_base_url=False`; the registry passes `None` when no override is supplied. Keep transport-specific configuration inside the adapter unless the shared runtime genuinely needs it. Never push provider wire-format branches into `AgentRuntime` or `HybridRouter`.

## Current registry

| Adapter ID | Status | Transport |
|---|---|---|
| `openai-compatible` | Implemented and covered by adapter tests | HTTPX Chat Completions endpoint, optional bearer API key |
| `anthropic` | Implemented and covered by adapter tests | HTTPX Messages API, `x-api-key` authentication |

Claude Code CLI, OpenAI Codex CLI and Gemini-native transports remain unimplemented. Anthropic uses the native Messages API; it is not routed through an OpenAI-compatible shim. An unknown adapter name fails during configuration; it is not silently converted into the OpenAI-compatible adapter.

CLI selection:
- Single provider: `--provider-adapter` / `NEXTORCA_PROVIDER_ADAPTER`
- Local endpoint: `--local-provider-adapter` / `NEXTORCA_LOCAL_PROVIDER_ADAPTER`
- Cloud endpoint: `--cloud-provider-adapter` / `NEXTORCA_CLOUD_PROVIDER_ADAPTER`

All default to `openai-compatible`. The Anthropic adapter defaults to `https://api.anthropic.com`; set `--base-url` only when using a compatible proxy or gateway.

## Compatibility checklist for a new adapter

Before implementing a native provider, obtain an explicit maintainer choice and record the exact API or CLI mode. Verify every item with official provider documentation and a mocked test before describing the adapter as supported.

| Area | Required contract questions | Minimum tests |
|---|---|---|
| Authentication | API key, OAuth/CLI login, environment variables, credential refresh and revocation | Missing/invalid credentials, secret never appears in exceptions/logs |
| Endpoint / model | Base URL, model IDs, regions, custom endpoints, context limit source | Request URL/model serialization and configuration validation |
| Messages | Supported roles, system/developer role handling, multimodal blocks and message-size constraints | Representative system/user/assistant/tool transcript and unsupported-shape rejection |
| Tools | Tool schema subset, strict mode, parallel calls, arguments encoding, stable call IDs and call order | No-tool, one-tool, multiple-tool, malformed schema/arguments, invalid call ID |
| Streaming | SSE/NDJSON format, partial JSON arguments, finish markers, usage frames, disconnect and cancellation | Ordered deltas, final turn exactly once, malformed/truncated frame, disconnect and cancellation |
| Errors | Permanent request/auth/schema errors vs transient rate limits, timeouts and service outages | 400/401/403 are not retried as availability; 408/429/5xx and transport errors map deliberately |
| Usage / limits | Input/output token counts, cached/reasoning tokens, rate limit headers, context windows | Missing/partial usage, non-negative counters, headers don't leak secrets |
| Privacy / routing | Local-only must never construct/call a cloud route; fallback is permitted only for transient local availability before any output | Forced local, local-only failure, no cloud calls; partial stream prevents provider switching |
| Lifecycle | HTTP session close, child process lifetime, cancellation, platform-specific process handling | Resource close, child termination and no orphan process |
| Terms / UX | Subscription/API distinction, user-visible setup, cost or usage limitations | Clear setup/errors; no claims about billing, access or capability that are not verified |

## Existing verification commands

```bash
uv run pytest tests/test_openai_compatible.py tests/test_provider_registry.py tests/test_hybrid_routing.py tests/test_hybrid_streaming.py tests/test_cli_routing_defaults.py -q
uv run ruff check nextorca tests evals examples
uv run python -m compileall -q nextorca examples evals
uv run pytest
```

## Selection gate

The maintainer selected Anthropic Messages API, Claude Code CLI, OpenAI Codex CLI and Gemini API on 2026-11-14. Implement each separately. A subscription CLI adapter and a provider HTTP API are different integrations with different credential, lifecycle, user-account and terms implications; do not infer one from the provider brand name. A CLI adapter must not bypass NextOrca permission checks or execute workspace tools outside the normalized runtime boundary.
