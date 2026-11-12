# Plan 001: Keep non-sandbox MCP validation in fast PR checks

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If a STOP condition occurs, stop and report instead of improvising. Keep this change in its own implementation PR.

> **Drift check (run first)**: `git diff --stat f207d19..HEAD -- tests/test_mcp_stdio.py tests/test_mcp_schema_validation.py`. If either in-scope file changed since this plan was written, compare the current code to the excerpts below before proceeding.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `f207d19`, 2026-11-12

## Why this matters

The lightweight PR workflow proposed in PR #20 deliberately does not install Bubblewrap. The module-level pytest skip in `tests/test_mcp_stdio.py` therefore skips the entire module when Bubblewrap is missing, including tests that only validate JSON configuration and never create an MCP client. This silently removes useful regression coverage from the required fast PR check. Keep the runtime sandbox requirement on the tests that actually launch the sandbox, while allowing pure manifest/configuration tests to run everywhere.

## Current state

- `.github/workflows/ci.yml` currently provisions Bubblewrap and AppArmor for every workflow run. PR #20 changes this to run the comprehensive sandbox setup only for scheduled/manual validation.
- `tests/test_mcp_stdio.py:135-138` applies one skip marker to every test in the module:

  ```python
  pytestmark = pytest.mark.skipif(
      not sys.platform.startswith("linux") or shutil.which("bwrap") is None,
      reason="MCP stdio tests require the Linux Bubblewrap sandbox.",
  )
  ```

- Several tests use only `load_mcp_config` and temporary files, so they do not need a live sandbox:
  - `test_mcp_config_requires_argv_array_and_valid_server_name` at lines 184–198.
  - `test_mcp_config_limits_server_count` at lines 201–208.
  - `test_mcp_manifest_rejects_oversized_configuration` at lines 313–317.
  - `test_mcp_manifest_network_and_writable_grants_are_typed` at lines 331 onward.
- Tests that create `MCPStdioClient` or use `_client(...)` do require Linux and Bubblewrap because the client constructor creates `LinuxBubblewrapSandbox`.
- Existing test style uses pytest functions, `tmp_path`, inline manifest construction, and `pytest.raises`; follow that style. See the four configuration tests listed above.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Focused MCP config tests | `uv run pytest tests/test_mcp_stdio.py -q -k 'mcp_config or mcp_manifest'` | Four configuration/manifest tests pass without Bubblewrap |
| Full tests | `uv run pytest` | Exit 0; only sandbox-dependent tests skip when Bubblewrap is absent |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |

## Scope

**In scope**
- `tests/test_mcp_stdio.py`

**Out of scope**
- `.github/workflows/ci.yml` — PR #20 owns the CI workflow split.
- `nextorca/mcp_stdio.py` and `nextorca/sandbox.py` — no runtime behavior change is needed.
- MCP protocol implementation, server lifecycle, and sandbox policy.

## Git workflow

- Branch: `fix/fast-mcp-config-tests`
- Keep this change in one focused commit / PR.
- Do not merge until the required `Quick checks` branch-protection check passes.

## Steps

### Step 1: Remove the module-wide skip

Remove the module-level `pytestmark` assignment at `tests/test_mcp_stdio.py:135-138`. Replace it with a reusable module constant or decorator that represents the Linux + Bubblewrap prerequisite, but do not apply it globally.

**Verify**: `uv run pytest tests/test_mcp_stdio.py -q -k 'mcp_config or mcp_manifest'` → all four config/manifest tests execute and pass without Bubblewrap.

### Step 2: Mark only sandbox-dependent tests

Apply the prerequisite marker to each test that constructs `MCPStdioClient`, enters `_client(...)`, or executes a real Bubblewrap process. Keep configuration-only tests unmarked. Re-read the full test module while making this classification; do not assume a test is pure merely because its name contains “config”.

**Verify**: On a host without Bubblewrap, `uv run pytest tests/test_mcp_stdio.py -q` → the four configuration/manifest tests pass; sandbox-dependent integration tests are reported as skipped. On a supported Linux host with Bubblewrap, those integration tests remain eligible to run.

## Test plan

- Confirm invalid server names and command-string manifests are rejected.
- Confirm the maximum server count is enforced.
- Confirm oversized configuration files are rejected.
- Confirm `network_access` and `writable_paths` are parsed and type-checked.
- Confirm tests that call `MCPStdioClient` remain gated by the sandbox prerequisite.

Use the existing configuration tests as patterns. Do not replace sandbox integration coverage with mocks.

## Done criteria

- [ ] The module-level skip is removed.
- [ ] The four configuration/manifest tests run and pass without Bubblewrap.
- [ ] Only tests that actually require Linux Bubblewrap are skipped on an unsupported host.
- [ ] `uv run pytest` exits 0.
- [ ] `uv run ruff check nextorca tests evals examples` exits 0.
- [ ] No files outside the scope list are modified.

## STOP conditions

Stop and report if:
- A supposedly configuration-only test constructs `MCPStdioClient`, starts a subprocess, or otherwise depends on Bubblewrap.
- The quick CI job from PR #20 changes its scope or begins installing Bubblewrap on PRs; reassess whether this plan still adds value.
- Passing the tests requires changing runtime behavior or sandbox policy.

## Maintenance notes

When adding MCP tests, decide explicitly whether the test needs an actual Bubblewrap process. Keep pure manifest, validation, and argument-contract tests runnable in the fast PR job; reserve only OS isolation/process integration tests for the comprehensive environment.
