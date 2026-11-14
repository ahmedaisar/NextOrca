# Plan 009: Build a repeatable real-repository coding-task evaluation harness

> **Executor instructions**: Implement a deterministic, opt-in benchmark harness for comparing NextOrca provider and routing configurations on reproducible repository tasks. Keep routine CI fast and network-free. Do not make live model calls unless the operator explicitly supplies the opt-in flag and credentials. Follow every step and verification gate; stop on any STOP condition.
>
> **Drift check (run first)**: `git diff --stat bbba47f..HEAD -- evals nextorca/routing.py nextorca/runtime.py nextorca/provider.py nextorca/provider_registry.py nextorca/session_store.py tests pyproject.toml .github/workflows/ci.yml`. If any listed file changed, compare the Current state below with live code before proceeding.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `bbba47f45689f9edfeb7d1beb100b6e95acca93a`, 2026-11-14

## Why this matters

NextOrca now has five provider adapters and deterministic local/cloud routing, but the current evaluation measures only the task classifier. It cannot tell whether a provider/model/route actually completes a coding task, passes the repository's tests, respects tool permissions, or offers a useful latency/cost trade-off. A small benchmark using disposable, reproducible repositories gives the maintainer evidence for choosing routing defaults and prioritizing provider parity without making every PR run slow or requiring live API credentials.

## Current state

- `evals/routing_cases.json` contains 28 prompt-to-task-class examples.
- `evals/evaluate_routing.py` calls `nextorca.routing.classify_task`, calculates classification accuracy and per-class counts, and exits nonzero below `--fail-under`. It does not instantiate an agent, provider or workspace.
- `nextorca/routing.py` exposes `classify_task` and `HybridRouter`; route decisions carry task, provider, model and reason.
- `nextorca/provider.py` defines `ChatProvider.complete` and the optional `StreamingChatProvider.stream_complete` protocol.
- `nextorca/runtime.py` owns the agent/tool loop and approval policy. `nextorca/workspace.py` constrains filesystem tools to a canonical workspace root.
- `tests/test_provider_registry.py` and provider-specific tests use stub providers, HTTPX MockTransport and fake CLI executables. Follow these deterministic patterns for the fast harness tests.
- `pyproject.toml` provides `uv sync --extra dev`, pytest and Ruff. Runtime dependencies currently include HTTPX and prompt-toolkit only.

The existing routing evaluator is a useful, fast unit-level check; preserve it. Add a separate task benchmark rather than replacing its accuracy metric.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Existing routing check | `uv run python evals/evaluate_routing.py` | Exit 0; accuracy at or above 90% |
| Tests | `uv run pytest -q` | All tests pass |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |
| CLI smoke | `uv run nextorca --help` | Exit 0 |

## Scope

**In scope**
- `evals/` — benchmark task manifest/schema, fixture repositories, runner, scoring and report output.
- `tests/` — unit tests for manifest validation, isolated workspaces, runner lifecycle, scoring and report redaction.
- `docs/` — benchmark usage, limitations and interpretation.
- Minimal dependency-free hooks in `nextorca/runtime.py`, `nextorca/routing.py` or `nextorca/types.py` only if needed to expose structured run telemetry without changing normal runtime behavior.
- A short CI smoke test for manifest validity and fake-provider execution, if it stays within the current fast PR budget.

**Out of scope**
- Live provider calls in CI or by default.
- A hosted benchmark service, web dashboard, leaderboard or telemetry upload.
- Changing default routing behavior based on benchmark results in this plan.
- Automatically modifying the source repositories or accepting generated patches.
- Adding more provider adapters.
- Putting long-running benchmark suites on every feature-branch commit.

## Suggested executor toolkit

- Use the existing fake-provider and mock-transport patterns; do not add a new evaluation framework unless the standard library and pytest cannot express the requirement.
- Treat benchmark task prompts, repository contents and model outputs as untrusted data.
- Reference the provider adapter contract in `docs/provider-adapter-contract.md`.

## Steps

### Step 1: Define a versioned benchmark task contract

Create a documented JSON task schema with stable task ID, description, fixture repository path or pinned Git revision, setup steps, prompt, allowed tools, verification argv, timeout, expected task category and optional scoring rubric. Validate types, bounds, path containment and argv shape before running anything. Do not execute shell text interpolated from task metadata; commands must be explicit argv arrays and must run only in a fresh disposable worktree/temp directory.

**Verify**: add schema tests for valid tasks, unknown versions, missing fields, path traversal, empty commands, excessive timeouts and malformed argv; `uv run pytest tests/test_evaluation_manifest.py -q` → all pass.

### Step 2: Add reproducible local fixture tasks

Create at least six small, deterministic fixture repositories covering a bug fix, feature addition, refactor, test repair, code explanation/read-only task and a security review. Each coding task must have a verification command that distinguishes a successful change from an unchanged repository. Keep fixtures small, license-compatible and independent of network services. Pin their initial contents in the repository.

**Verify**: `uv run pytest tests/test_evaluation_fixtures.py -q` → all fixtures initialize in temporary directories and each verification command has the documented expected baseline result.

### Step 3: Implement isolated task execution with fake-provider coverage

Add an evaluator that constructs the existing NextOrca runtime/provider interfaces for each configured adapter and route mode. Run each task in a fresh disposable worktree or copied fixture; enforce task timeout, per-task iteration/tool-call caps and cleanup in `finally`. Do not share a mutable worktree between models. Keep all mutating operations inside the disposable directory. Add a fake provider that produces a known tool-call sequence so the runner can be tested without network access.

The evaluator must record the actual route decision, selected adapter/model, exit code, elapsed duration, tool-call counts, verification result and any usage fields the provider actually reports. Missing usage/cost data must remain null/unknown, never be estimated or fabricated.

**Verify**: `uv run pytest tests/test_evaluation_runner.py -q` → fake-provider tasks complete deterministically; timeout and cleanup tests pass; no external network is required.

### Step 4: Score results and emit machine-readable reports

Emit one JSON result per task/run plus an aggregate JSON summary. Include benchmark version, source commit, fixture revision, provider adapter, model identifier, route mode, task outcome, verification command/result, latency, usage, tool-call counts and sanitized failure category. Add aggregate task success rate, verification pass rate, per-category results and median/p95 latency when sample counts permit. Do not store prompts, raw model transcripts, environment variables, API keys or complete command output by default. Make verbose transcript capture an explicit local-only opt-in with credential redaction.

**Verify**: `uv run pytest tests/test_evaluation_reports.py -q` → stable schema, deterministic aggregate metrics, null handling and secret-redaction tests pass.

### Step 5: Add a live benchmark command that is explicitly opt-in

Expose a separate command such as `uv run python -m evals.run_benchmark` with explicit adapter/model/route/task selection. Require `--live` before constructing real network-backed providers; otherwise use the fake provider or fail with an actionable message. Never run paid models, create remote sandboxes or upload artifacts from a normal test invocation. Document credentials as environment variables without printing their values.

**Verify**: `uv run python -m evals.run_benchmark --help` → help exits 0; invocation without `--live` never attempts a network connection; fake mode succeeds.

### Step 6: Integrate a fast, non-blocking CI smoke check

Add only manifest validation and a short fake-provider smoke run to the existing lightweight PR workflow. Do not run the live benchmark, full repository fixture matrix or provider account tests in PR CI. Keep the existing CI's comprehensive/slow validation policy unchanged.

**Verify**: `uv run pytest tests/test_evaluation_manifest.py tests/test_evaluation_runner.py -q` → all pass; inspect the workflow diff to confirm no network/paid benchmark job was added to each PR.

## Test plan

- New tests: manifest schema and path validation; fixture setup; fake provider completion; isolated worktree cleanup; timeout and iteration caps; tool-call safety; route capture; aggregate metrics; deterministic serialization; missing usage handling; secret redaction; no-network default.
- Model the provider fixtures on `tests/test_provider_registry.py`, `tests/test_anthropic.py` and `tests/test_gemini.py`.
- Keep tests hermetic: no real API credentials, network requests, paid calls or remote infrastructure.
- Verification: `uv run pytest -q` → all tests pass, including the new evaluator suite.

## Done criteria

- [ ] Existing routing classifier evaluator still passes unchanged.
- [ ] At least six deterministic fixture tasks cover the stated task categories.
- [ ] Fake-provider benchmark runs end-to-end without network access.
- [ ] Each task runs in an isolated disposable workspace with enforced timeout and cleanup.
- [ ] Machine-readable per-run and aggregate reports are deterministic and redact secrets.
- [ ] Live provider execution requires an explicit opt-in flag.
- [ ] Routine CI runs only a fast fake-provider smoke test; no live provider calls.
- [ ] `uv run ruff check nextorca tests evals examples` exits 0.
- [ ] `uv run python -m compileall -q nextorca examples evals` exits 0.
- [ ] `uv run pytest -q` exits 0.
- [ ] `uv run nextorca --help` exits 0.

## STOP conditions

Stop and report if:
- The current runtime cannot be constructed with a fake provider without performing side effects or prompting for interactive approval.
- The only viable task execution design requires running untrusted fixture code on the host outside an isolated disposable worktree.
- Task definitions require arbitrary shell strings rather than validated argv.
- A useful metric would require capturing secrets, private transcripts or uploading data by default.
- The existing CI workflow has changed so the proposed smoke check would materially increase PR latency.

## Maintenance notes

Keep benchmark tasks versioned and small; changes to task prompts or verification commands change benchmark meaning and should increment the corpus version. Report provider-reported usage only. Compare configurations on identical fixtures and task revisions. Do not promote a model or route to default based on one run; require repeated runs and report variance. Full live evaluation remains an operator-invoked workflow, not a CI gate.
