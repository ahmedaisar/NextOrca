# Plan 010: Add an opt-in Vercel Sandbox execution backend

> **Executor instructions**: Add Vercel Sandbox as an optional remote execution backend for approved project commands. Preserve local execution as the default and preserve the existing Linux Bubblewrap fail-closed boundary for MCP stdio. This plan does not turn Vercel into a required dependency or claim that local workspace file operations are remote. Verify the current official Python SDK/API before coding; do not guess SDK methods.
>
> **Drift check (run first)**: `git diff --stat bbba47f..HEAD -- nextorca/sandbox.py nextorca/shell.py nextorca/workspace.py nextorca/mcp_stdio.py nextorca/cli.py pyproject.toml tests docs`. If any in-scope file changed, compare the Current state with live code.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/009-real-repository-evaluation-harness.md (for deterministic command/result evaluation)
- **Category**: direction
- **Planned at**: commit `bbba47f45689f9edfeb7d1beb100b6e95acca93a`, 2026-11-14

## Why this matters

NextOrca currently executes approved shell commands with the user's OS permissions, while MCP stdio integrations require Linux Bubblewrap and deliberately have no unsandboxed fallback. An optional Vercel Sandbox backend would let users run supported repository commands in an isolated remote Linux environment, including from platforms where local Bubblewrap is unavailable. It must remain opt-in, visibly remote, explicitly permissioned and separate from local-only model privacy: sending code to a remote sandbox is a data transfer even if model inference remains local.

## Current state

- `nextorca/sandbox.py` defines `LinuxBubblewrapSandbox`; it rejects non-Linux platforms and missing Bubblewrap with `SandboxError`, and does not fall back to unsandboxed execution.
- `nextorca/mcp_stdio.py` constructs `LinuxBubblewrapSandbox` for MCP stdio servers. Preserve this behavior; do not silently replace it with a remote service or weaken its security guarantees.
- `nextorca/shell.py` exposes approved command execution for the local workspace. Its command display, argv validation, permission policy and output handling are the existing local execution contract.
- `nextorca/workspace.py` resolves filesystem paths within the local workspace and prepares user-approved file operations. It is not a remote filesystem abstraction.
- `pyproject.toml` has no Vercel SDK dependency today. Keep local installs lightweight by adding any Vercel SDK as an optional extra, not a mandatory runtime dependency.
- Official Vercel documentation describes persistent named sandboxes, snapshots, configurable network policy, regions and drives. The Python documentation exposes `from vercel import sandbox`; confirm the currently supported package version and exact APIs before implementation.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Tests | `uv run pytest -q` | All tests pass |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |
| CLI smoke | `uv run nextorca --help` | Exit 0 |

## Suggested executor toolkit

- Official docs: https://vercel.com/docs/sandbox/concepts, https://vercel.com/docs/sandbox/sdk-reference, https://vercel.com/docs/sandbox/concepts/network-policy and https://vercel.com/docs/sandbox/concepts/persistent-sandboxes.
- Verify the Vercel Python SDK's installed/published documentation and examples for sandbox creation, command execution, file transfer, stop/resume and snapshots. Never infer Python API names from TypeScript examples.
- Use a Vercel Sandbox integration test only when a dedicated opt-in environment flag and credentials are present; CI must use a fake backend.

## Scope

**In scope**
- A new execution-backend protocol/module, for example `nextorca/execution.py`, and a local backend that preserves current shell semantics.
- A Vercel Sandbox implementation behind an optional `vercel` dependency extra and explicit configuration.
- `nextorca/shell.py` and `nextorca/cli.py` only for backend selection and clear remote-execution UX.
- Fake-backend tests, SDK adapter tests and opt-in Vercel integration tests.
- Documentation describing data transfer, network policy, regions, persistence, costs and limitations.

**Out of scope**
- Replacing or weakening `LinuxBubblewrapSandbox` for MCP stdio.
- Making Vercel mandatory or changing the default from local execution.
- Silently sending a local workspace, secrets, environment variables or prompts to Vercel.
- Uploading a dirty workspace or private Git repository until a safe authenticated transfer design is verified and explicitly approved by the operator.
- Running production deployments, provisioning databases or storing session history in this plan.
- Treating `local-only` model privacy as permission to upload source code to a remote sandbox.

## Steps

### Step 1: Verify Vercel Sandbox SDK capabilities and define the boundary

Read current official Python SDK documentation and inspect the exact package version/API. Confirm sandbox create/resume, command argv execution, timeout/cancellation, stdout/stderr/exit code, network policy, region selection, snapshots and file transfer. Write down which operations are supported by the installed SDK. If private repository authentication or local uncommitted workspace transfer cannot be performed without exposing credentials, explicitly leave those unsupported.

MVP boundary: remote execution is allowed only against an explicitly configured remote checkout/snapshot whose source the user has authorized. No automatic local workspace upload or Git push. A returned patch/artifact must be shown and approved before it is applied locally.

**Verify**: add a documented SDK capability table with source links and exact verified API names; a no-credential import/help smoke check exits 0 when the optional extra is installed.

### Step 2: Introduce a narrow execution backend contract

Create an interface that accepts validated argv, working directory identifier, timeout, network policy and a bounded environment allowlist, and returns a structured result containing stdout, stderr, exit code, duration and backend identity. Implement a local backend that delegates to the existing approved shell execution path without changing its behavior. Do not move tool permission decisions into the backend.

**Verify**: `uv run pytest tests/test_execution_backend.py -q` → local backend tests prove argv, timeout, result and approval behavior are unchanged.

### Step 3: Implement the Vercel Sandbox adapter

Implement the adapter using the verified Python SDK. Require explicit `VERCEL_TOKEN` or supported Vercel OIDC authentication plus project/team scope as required by the SDK. Use named sandboxes only when persistence is explicitly enabled; otherwise prefer ephemeral sessions. Configure a bounded timeout and explicit region. Default network policy to deny-all; allow network only when the operator enables it and supplies a reviewed domain allowlist. Never pass the host's complete environment into the sandbox.

Do not include API tokens in argv, shell output, structured result logs, prompts or session events. Do not accept arbitrary user-supplied sandbox IDs outside the configured project/team. Clean up sessions in `finally`; persist only the minimum metadata required to resume a deliberately persistent sandbox.

**Verify**: fake SDK tests cover creation, region, network deny-by-default, argv, environment allowlist, timeout, cancellation, stop/cleanup and error mapping; `uv run pytest tests/test_vercel_sandbox.py -q` → all pass.

### Step 4: Add explicit CLI selection and safety UX

Add a backend selector with `local` as the default and `vercel` as an explicit option. Before the first remote command in a session, show the remote project/region, source revision, network policy and the fact that source/command data leaves the machine; require an affirmative approval. Keep shell command approval separate from remote-execution consent. Reject Vercel backend selection when required project/team/auth configuration is absent. Do not silently fall back to local execution after a remote failure or vice versa.

**Verify**: CLI tests assert default local selection, explicit Vercel selection, missing-config failure, remote consent denial, no fallback and redacted credential errors.

### Step 5: Add opt-in integration and operational documentation

Add a live integration test gated by `NEXTORCA_VERCEL_INTEGRATION=1`; it must create an ephemeral sandbox, run a harmless command, verify the structured result and clean up. Document required Vercel project/team/token settings, optional region, sandbox timeout, snapshot retention, network policy, cost considerations and supported source modes. Do not make live integration part of PR CI.

**Verify**: with no integration flag, `uv run pytest -q` makes no Vercel calls; with the flag and credentials, the smoke test reports a sandbox command result and cleanup.

## Test plan

- Unit tests for local and fake Vercel backends, command argv validation, output bounds, timeout, cancellation, no-fallback semantics, explicit remote consent and credential redaction.
- Test that MCP stdio still requires the existing Linux Bubblewrap sandbox and never uses Vercel implicitly.
- Optional live integration test is skipped unless explicitly enabled.
- Model fake adapter tests on `tests/test_mcp_stdio.py` and the fake-process tests for `tests/test_claude_code_cli.py` / `tests/test_codex_cli.py`.

## Done criteria

- [ ] Local backend remains the default and its approval behavior is unchanged.
- [ ] Vercel backend is optional and cannot be selected without explicit configuration and remote-consent approval.
- [ ] Remote execution uses validated argv, bounded timeout and a minimal environment allowlist.
- [ ] Network policy is deny-all by default; enabling egress requires explicit configuration.
- [ ] No host workspace upload, private repo credential transfer or silent Git push is introduced.
- [ ] MCP stdio retains Linux Bubblewrap fail-closed behavior.
- [ ] No implicit local/remote fallback occurs on errors.
- [ ] All fake backend tests pass; live integration is opt-in only.
- [ ] `uv run ruff check nextorca tests evals examples`, compileall, `uv run pytest -q` and `uv run nextorca --help` exit 0.

## STOP conditions

Stop and report if:
- The Python SDK cannot enforce the network policy, timeout or command result contract required here.
- The SDK requires credentials in a command string, environment dump or persisted session record.
- A proposed implementation uploads the user's local workspace or private repository without a separately approved design.
- Remote sandbox commands could bypass existing command approval or execute against a different repository revision than shown to the user.
- The only approach weakens the existing Bubblewrap fail-closed behavior.

## Maintenance notes

Vercel Sandbox is a remote compute service with its own regions, quotas, snapshot retention and pricing. Re-check current SDK and platform limits before each SDK upgrade. Keep local execution independent. A remote sandbox is not equivalent to local-only privacy; UI copy and docs must remain explicit about source transfer and network egress.
