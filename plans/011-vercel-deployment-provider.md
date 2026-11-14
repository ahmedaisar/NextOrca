# Plan 011: Add an explicit Vercel deployment provider

> **Executor instructions**: Implement Vercel deployment operations for Git-connected projects. NextOrca is a Python terminal CLI, not a Vercel-hosted web application; this feature lets the user deploy an application repository they are working on. Default to preview deployments. Production deploys require an explicit, separate confirmation. Do not push commits or create Vercel projects without operator approval.
>
> **Drift check (run first)**: `git diff --stat bbba47f..HEAD -- nextorca/cli.py nextorca/config.py nextorca/__main__.py pyproject.toml tests README.md docs`. If paths differ or have changed, reconcile before implementation.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `bbba47f45689f9edfeb7d1beb100b6e95acca93a`, 2026-11-14

## Why this matters

NextOrca can modify and verify code but has no deployment workflow in its Python CLI. A Vercel integration would close part of the coding loop for users building applications hosted on Vercel: inspect project configuration, create a preview deployment from a pushed Git revision, follow build status and report the URL/logs. The integration must not pretend a local dirty tree is deployed or push code on the user's behalf without a distinct approval.

## Current state

- `nextorca/cli.py` builds the terminal agent and parser; the project exposes a single `nextorca` console script from `pyproject.toml`.
- `README.md` describes NextOrca as a local-first terminal coding agent; it does not claim a web-hosted NextOrca service.
- `pyproject.toml` already depends on HTTPX, so the first implementation can use HTTPX for the Vercel REST API without a mandatory Node SDK.
- No Vercel deployment client, Vercel project config reader, deployment command or deployment tests were found in the current baseline.
- Vercel's REST API supports creating deployments from a Git source (provider, organization, repository, ref and commit SHA) and reading deployment status. A Git-connected project must exist and the referenced commit must be available to Vercel.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Tests | `uv run pytest -q` | All tests pass |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |
| CLI smoke | `uv run nextorca --help` | Exit 0 |

## Suggested executor toolkit

- Official API reference: https://vercel.com/docs/rest-api/reference/endpoints/deployments/create-a-new-deployment and https://vercel.com/docs/rest-api/reference/endpoints/deployments/get-a-deployment.
- Verify current API fields, authentication scopes, response states and rate limits before implementing. Prefer HTTPX, already used by NextOrca, over adding a large SDK solely for deployment requests.

## Scope

**In scope**
- A small Vercel API client module, for example `nextorca/vercel/deployments.py`.
- CLI subcommands such as `nextorca vercel projects`, `nextorca vercel deploy` and `nextorca vercel deployment <id>`, matching existing command parsing conventions.
- Configuration for Vercel token, team ID, project ID/name and default deployment target.
- Tests using HTTPX MockTransport or an injected client.
- README and docs for Git project linking, required credentials, preview/production workflow and limitations.

**Out of scope**
- Hosting NextOrca itself as a web service or converting the Python CLI into a Vercel Function.
- Uploading local workspace files or binary assets through inline deployment in this plan.
- Automatically committing or pushing a user's working tree.
- Automatically creating projects, linking arbitrary repositories or modifying domains/environment variables.
- Production deployment without explicit user approval.
- Database provisioning, Blob storage or remote sandbox creation (handled by separate plans).

## Steps

### Step 1: Verify Vercel deployment API contract and config model

Read the current official REST API docs for deployment creation, status lookup, cancellation and deployment logs. Confirm the exact Git source schema, token authorization, team/project scoping and final status values. Define a typed configuration object; resolve credentials from `VERCEL_TOKEN` only and never serialize them into CLI config, SQLite events or logs.

Support only a Git-connected project and a commit/ref that already exists remotely. Detect dirty working trees and refuse deployment unless the user explicitly chooses a pushed commit; do not deploy HEAD if it is not present in the remote repository.

**Verify**: config tests cover missing token/project, invalid target, dirty/unpushed commit and secret redaction; API contract tests use mocked responses.

### Step 2: Implement a bounded HTTPX Vercel API client

Create a client that applies bearer authentication, explicit team/project scope, request timeout, response-size bounds and sanitized error handling. Implement deployment creation from a configured Git source, deployment detail/status retrieval and bounded build-log/event retrieval. Distinguish authentication/configuration errors from rate limits and transient platform failures. Never include the token in exception messages or request debug logs.

**Verify**: `uv run pytest tests/test_vercel_deployments.py -q` → request URL/body/auth scope and error classification pass using HTTPX MockTransport.

### Step 3: Add a preview-first CLI workflow

Add commands to inspect the configured Vercel project, create a preview deployment from a selected pushed branch/commit and inspect a deployment's status/URL. The CLI must print the source repository/ref/SHA and target before creation and require confirmation. Production target requires a separate explicit `--production` flag plus interactive confirmation; a non-interactive invocation must fail closed unless an explicit confirmation flag is supplied.

Poll deployment status with bounded exponential backoff and a maximum wait duration. Stop on READY, ERROR, CANCELED or timeout. Return a nonzero exit code for failed/canceled/timed-out deployments. Do not assign aliases or alter production domains in this plan.

**Verify**: CLI tests cover preview default, production confirmation, no confirmation in non-interactive mode, status polling, timeout, failure exit codes and no hidden push.

### Step 4: Document Git integration and operator workflow

Document that Vercel deployment requires a Git-connected project and a pushed commit. Explain that preview is the default, production is an explicit action, local uncommitted changes are not uploaded, and project creation/Git linking remains a dashboard/owner step unless separately approved. Add environment-variable names without values.

**Verify**: docs accurately describe implemented commands and tests; `uv run nextorca vercel --help` and `uv run nextorca --help` exit 0.

## Test plan

- HTTPX MockTransport tests for success, malformed response, unauthorized/forbidden, rate limiting, transient server errors and timeout.
- CLI tests for dirty tree rejection, pushed revision selection, preview default, production confirmation and bounded polling.
- Secret-redaction tests assert the token is absent from errors, output and persisted session events.
- No live Vercel API calls in CI.

## Done criteria

- [ ] User can inspect a configured Git-connected Vercel project.
- [ ] User can create and follow a preview deployment for a pushed commit.
- [ ] Production deploy requires a distinct explicit confirmation.
- [ ] Dirty/unpushed local changes are never misrepresented as deployed.
- [ ] No implicit commit, push, project creation, alias or domain change occurs.
- [ ] Vercel token is never logged, persisted or included in exceptions.
- [ ] Mocked API and CLI tests cover expected lifecycle and failures.
- [ ] `uv run ruff check nextorca tests evals examples`, compileall, `uv run pytest -q` and CLI help exit 0.

## STOP conditions

Stop and report if:
- The configured Git provider/project cannot resolve the selected remote commit unambiguously.
- The API requires permissions broader than deployment creation/status for the planned scope.
- The local Git remote differs from the configured Vercel project source.
- Safe production confirmation cannot be enforced for non-interactive invocations.
- The current Vercel API schema materially differs from the documented fields; do not guess.

## Maintenance notes

Vercel API fields, scopes and deployment lifecycle states can change. Keep the API client isolated from the agent runtime. Later work may add deployment log streaming, domains, environment variables or direct upload, but each is a separate permissioned capability. A Vercel project should be explicitly linked and reviewed by its owner.
