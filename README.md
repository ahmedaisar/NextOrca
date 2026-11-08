# NextOrca

**A local-first terminal coding agent for working directly in your projects, with local and cloud models behind one agent experience.**

[![CI](https://github.com/ahmedaisar/NextOrca/actions/workflows/ci.yml/badge.svg)](https://github.com/ahmedaisar/NextOrca/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)

Run `nextorca` inside a project to start an interactive coding session. Ask it to inspect and change code, run project commands, and iterate on test failures. Local/cloud orchestration stays behind the same terminal agent experience.

> **Project status:** personal project, under active development. Shell commands run with your user account permissions and are shown for approval before execution.

## Contents

- [Features](#features)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Examples](#examples)
- [Skills](#skills)
- [Plugins](#plugins)
- [Context management](#context-management)
- [Configuration](#configuration)
- [Contributing](#contributing)
- [Limitations and security](#limitations-and-security)
- [License](#license)

## Features

- **Provider-neutral runtime:** connect to local or hosted OpenAI-compatible APIs.
- **Hybrid routing:** route codebase exploration to a local model and more demanding coding tasks to a cloud model, with manual local/cloud overrides.
- **Privacy mode:** `local-only` prevents prompts and tool context from being sent to a cloud provider.
- **Interactive terminal agent:** launch without a prompt to start a persistent conversation.
- **Streaming responses:** compatible providers can stream assistant text directly into the terminal.
- **Long-session context:** compact conversation history into a structured summary without deleting the stored transcript.
- **Coding tools:** read, search, edit files and run project commands with explicit approval.
- **Agent Skills:** discover compatible SKILL.md guides from your project or user skill folders and load them on demand.
- **Local plugins:** bundle skills and approval-gated command tools using a versioned JSON manifest.
- **Approval-gated edits:** interactive sessions expose file creation and exact-text edits with a diff approval before each change; one-shot mode stays read-only by default.
- **Undo checkpoints:** inspect approved changes and undo a checkpoint when the target file has not changed since.
- **Persistent sessions:** SQLite-backed session history and resumable session IDs.
- **Local observability:** inspect provider, latency, token-usage, and routing metrics without sending telemetry to an analytics service.
- **MCP stdio integrations (experimental):** explicitly configured servers run in a Linux Bubblewrap sandbox; each external tool call requires interactive approval.

## Installation

### Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- An OpenAI-compatible model endpoint:
  - a local server such as [llama.cpp](https://github.com/ggml-org/llama.cpp), or
  - a hosted provider with an API key

### Install from source

```bash
git clone https://github.com/ahmedaisar/NextOrca.git
cd NextOrca

# Install the package and development dependencies
uv sync --extra dev

# Confirm the CLI is available
uv run nextorca --help
```

To install only runtime dependencies in an existing checkout, use `uv sync`.

## Quickstart

### 1. Start an OpenAI-compatible endpoint

For a local endpoint, start your preferred inference server and note its API base URL and model identifier. For example, a llama.cpp server commonly exposes an endpoint at `http://127.0.0.1:8080/v1`.

### 2. Run NextOrca against a workspace

```bash
uv run nextorca \
  --base-url http://127.0.0.1:8080/v1 \
  --model your-local-model \
  --workspace ./path/to/your-repository \
  "Explain the main modules and how they fit together."
```

Interactive mode provides read, search, edit and shell tools. File edits show a diff and shell commands show the exact command before asking for approval.

### 3. Start an interactive coding session

```bash
uv run nextorca --workspace ./path/to/your-repository
```

Type requests naturally. Use `/help`, `/session`, `/new`, `/tools`, `/mcp`, `/plugins`, `/route`, `/privacy`, `/goal`, and `/exit`. Ctrl-C interrupts a request; Ctrl-D exits.

### 4. Connect a hosted provider (optional)

```bash
export NEXTORCA_BASE_URL=https://openrouter.ai/api/v1
export NEXTORCA_API_KEY=your-api-key
export NEXTORCA_MODEL=your-provider/model

uv run nextorca --workspace ./path/to/your-repository \
  "Find the retry logic and explain its failure modes."
```

Use your provider's own compatible base URL, model identifier, and API key variable as appropriate. Avoid committing secrets to source control.

## Examples

### Start the terminal agent

```bash
cd ./my-repo
uv run nextorca
```

### Explore a codebase

```bash
uv run nextorca --workspace ./my-repo \
  "Map the package structure and identify the application entry points."
```

### Enable reviewed file edits

```bash
uv run nextorca --allow-edits --workspace ./my-repo \
  "Update the version string in pyproject.toml."
```

NextOrca displays a proposed diff and requires interactive approval before applying a file mutation.

### Use hybrid local/cloud routing

```bash
export NEXTORCA_LOCAL_BASE_URL=http://127.0.0.1:8080/v1
export NEXTORCA_LOCAL_MODEL=your-local-model

export NEXTORCA_CLOUD_BASE_URL=https://openrouter.ai/api/v1
export NEXTORCA_CLOUD_MODEL=your-provider/cloud-model
export NEXTORCA_CLOUD_API_KEY=your-api-key

uv run nextorca --route-mode auto --workspace ./my-repo \
  "Explain the authentication flow."

# Force all inference to remain local
uv run nextorca --route-mode local --privacy-mode local-only \
  --workspace ./my-repo "Review the module structure."
```

Routing uses a deterministic request classifier, not learned confidence scoring. Use `--route-mode local` or `--route-mode cloud` to override automatic decisions.

### Resume a session and inspect metrics

The CLI prints a session ID after a run. Save it and resume later:

```bash
uv run nextorca --workspace ./my-repo --session-id YOUR_SESSION_ID \
  "Continue investigating the database adapter."

uv run nextorca --workspace ./my-repo --session-stats
uv run nextorca --workspace ./my-repo --session-id YOUR_SESSION_ID --session-stats
```

### List and undo approved changes

```bash
uv run nextorca --workspace ./my-repo --list-checkpoints
uv run nextorca --workspace ./my-repo --undo-checkpoint CHECKPOINT_ID
```

Undo refuses to overwrite a file that has changed since the checkpoint was created.

### Configure an MCP stdio server (Linux only; experimental)

MCP is disabled unless both a server manifest and `--allow-mcp-tools` are supplied. Copy the example manifest, configure a command that is installed on your machine, and run:

```bash
cp mcp-servers.example.json mcp-servers.json
# Edit the server command, working directory, and allowed environment variables.
uv run nextorca --workspace ./my-repo \
  --mcp-config ./mcp-servers.json \
  --allow-mcp-tools \
  "Use the configured integration to inspect the project."
```

MCP subprocesses require Linux and Bubblewrap. They run with isolated namespaces, dropped capabilities, a read-only workspace by default, and no network access unless explicitly enabled. Every external tool call requires interactive approval. See the manifest example and the [MCP sandbox notes](#limitations-and-security).

## Skills

NextOrca discovers Agent Skills in these project locations:

- `.agents/skills/<skill-name>/SKILL.md`
- `.claude/skills/<skill-name>/SKILL.md`
- `.nextorca/skills/<skill-name>/SKILL.md`
- `~/.nextorca/skills/<skill-name>/SKILL.md` for user-wide skills

Each SKILL.md starts with simple YAML frontmatter containing a name and description:

```markdown
---
name: test-first
description: Run focused tests before and after making code changes.
---

# Test-first workflow

1. Find the tests closest to the code being changed.
2. Run the focused tests before editing when practical.
3. Make the smallest useful change.
4. Run focused tests again and report the actual result.
```

Only skill names and descriptions are added to the agent's initial context. The full instructions are loaded only when the agent selects a matching skill. Project skills take precedence over user-wide skills with the same name. Skill files are guidance, not a permission mechanism: they cannot bypass tool approvals.

See [the skills guide](docs/skills.md) for details.

## Goal mode

Use goal mode for multi-step tasks that should not be considered complete until checks and an independent review pass:

```text
/goal Fix the login refresh bug and add a regression test --verify uv run pytest tests/auth -q
/goal status
/goal resume
```

NextOrca asks the worker to signal completion, runs the supplied verification command after approval, then starts a fresh read-only reviewer session with access to workspace tools and the git diff. If verification or review fails, feedback is sent back to the worker for another attempt. Goal state is recorded in the session event log.

The reviewer is a second model pass, not a formal proof. Without a supplied verification command, automated verification is skipped and the reviewer must still explicitly approve.

## Local/cloud routing

NextOrca can use a local OpenAI-compatible endpoint and a hosted endpoint behind the same interactive agent. Configure both, then start with `--route-mode auto`:

```bash
export NEXTORCA_LOCAL_BASE_URL=http://127.0.0.1:8080/v1
export NEXTORCA_LOCAL_MODEL=your-local-model
export NEXTORCA_CLOUD_BASE_URL=https://openrouter.ai/api/v1
export NEXTORCA_CLOUD_MODEL=your-provider/cloud-model
export NEXTORCA_CLOUD_API_KEY=your-api-key

uv run nextorca --route-mode auto
```

When both local and cloud endpoint environment variables are present, the default route mode is now `auto`. The same terminal session and tools are used whichever provider handles a turn. Route choices are shown in the terminal. Use `/route local`, `/route cloud`, or `/route auto` to override for the current session, and `/privacy local-only` to prevent cloud routing and fallback.

Auto routing currently uses an explainable task classifier: exploration/explanation prefers local; edits, debugging, testing and review prefer cloud. A local outage may fall back to cloud only before any partial stream output. Local-only mode never falls back.

## Context management

Long coding sessions can accumulate tool output and old discussion. Use:

```text
/context
/compact
```

NextOrca asks the configured provider to summarize the objective, constraints, decisions, files, verified commands/results and remaining work. The summary is saved as an append-only session event. Original messages remain in SQLite; subsequent model requests use the summary plus recent complete message/tool-call turns.

Compaction is a model-generated aid, not a perfect transcript replacement. Review the summary if an important detail seems missing.

## Plugins

Plugins are local folders containing a `plugin.json` manifest. NextOrca discovers project plugins in `.nextorca/plugins/<plugin-id>/` and user plugins in `~/.nextorca/plugins/<plugin-id>/`.

A plugin can bundle Agent Skills and command-backed tools. Plugin tools are registered with the normal tool registry and require explicit approval for every invocation. Commands use argv arrays, not a shell string, and run with your user permissions in the current project directory.

See [the plugin guide](docs/plugins.md) and [the example plugin](examples/plugins/git-helper).

## Configuration

The single-provider mode accepts these options:

| Option | Environment variable | Purpose |
|---|---|---|
| `--base-url` | `NEXTORCA_BASE_URL` | OpenAI-compatible API base URL |
| `--model` | `NEXTORCA_MODEL` | Model identifier |
| `--api-key` | `NEXTORCA_API_KEY` | Provider API key |
| `--workspace` | — | Workspace root (defaults to current directory) |
| `--max-turns` | — | Maximum agent turns |
| `--session-db` | `NEXTORCA_SESSION_DB` | SQLite session database path |
| `--session-id` | `NEXTORCA_SESSION_ID` | Resume an existing session |
| `--verbose` | — | Emit structured runtime and routing events to stderr |

Hybrid mode additionally supports `NEXTORCA_LOCAL_BASE_URL`, `NEXTORCA_LOCAL_MODEL`, `NEXTORCA_LOCAL_API_KEY`, `NEXTORCA_CLOUD_BASE_URL`, `NEXTORCA_CLOUD_MODEL`, and `NEXTORCA_CLOUD_API_KEY`. `OPENROUTER_API_KEY` is accepted as a cloud-key fallback.

Useful permission and maintenance options:

- `--allow-edits`: expose Write/Edit tools with interactive diff approval.
- `--mcp-config PATH` and `--allow-mcp-tools`: opt into configured MCP servers.
- `--privacy-mode local-only`: prevent cloud routing.
- `--list-checkpoints`, `--undo-checkpoint ID`: inspect or undo approved file changes.
- `--session-stats`: display locally stored usage metrics.

Run `uv run nextorca --help` for the complete current CLI reference.

## Contributing

Contributions are welcome. Please keep changes focused, preserve the default-deny permission model, and update tests and documentation when behavior changes.

### Development setup

```bash
git clone https://github.com/ahmedaisar/NextOrca.git
cd NextOrca
uv sync --extra dev
```

### Validate changes

```bash
uv run ruff check scripts nextorca tests evals
uv run python -m compileall -q nextorca scripts
uv run pytest
uv run python evals/evaluate_routing.py --fail-under 0.95
```

The GitHub Actions workflow also validates the package, shell scripts, CLI, routing evaluation, and test suite. MCP sandbox tests require a Linux runner with Bubblewrap; Ubuntu hosts may additionally need a Bubblewrap-scoped AppArmor user-namespace profile.

### Pull requests

1. Create a focused branch from the latest `main`.
2. Include tests for bug fixes and new behavior.
3. Update the README or relevant documentation for user-visible changes.
4. Run the validation commands above.
5. Open a pull request describing the motivation, implementation, security implications, and test results.

Do not include API keys, credentials, private repository data, or generated session databases in commits. For security-sensitive issues, avoid publishing exploit details in a public issue before maintainers have had a chance to assess them.

## Limitations and security

- The agent runtime is experimental and is not a guarantee of autonomous coding correctness.
- Built-in file tools are workspace-scoped. File edits are opt-in, diff-reviewed, and checkpointed. General-purpose shell execution is not enabled by the built-in runtime.
- Hybrid routing uses a deterministic classifier; it does not estimate model confidence or provider cost.
- Local usage metrics remain in the SQLite database. Token counts depend on provider usage metadata; cost is not estimated.
- MCP integrations are experimental and Linux-only. Bubblewrap is mandatory; there is no unsandboxed fallback. The sandbox is not a virtual machine and does not impose comprehensive CPU, memory, or process quotas.
- MCP writable-path grants allow the configured server to write directly to those directories; those writes do not pass through NextOrca's file diff and undo workflow.
- Only configure MCP commands you trust. Server descriptions, instructions, and tool outputs are untrusted input.
- Cross-platform sandbox backends, broader interoperability testing, and stronger resource isolation remain future work.

## License

NextOrca is distributed under the [MIT License](LICENSE).
