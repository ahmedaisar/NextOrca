<div align="center">
  <img src="assets/loco_operator.png" width="55%" alt="NextOrca and the LocoOperator-4B model" />
</div>

<br>

# NextOrca

**A local-first coding-agent runtime built on the LocoOperator-4B code-exploration model.**

<div align="center">

[![MODEL](https://img.shields.io/badge/Model-FFB300?style=for-the-badge&logo=huggingface&logoColor=white)](https://huggingface.co/LocoreMind/LocoOperator-4B)
[![GGUF](https://img.shields.io/badge/GGUF-FF6F00?style=for-the-badge&logo=huggingface&logoColor=white)](https://huggingface.co/LocoreMind/LocoOperator-4B-GGUF)
[![Blog](https://img.shields.io/badge/Blog-4285F4?style=for-the-badge&logo=google-chrome&logoColor=white)](https://locoremind.com/blog/loco-operator)
[![GitHub](https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/ahmedaisar/NextOrca)
[![Colab](https://img.shields.io/badge/Colab-F9AB00?style=for-the-badge&logo=googlecolab&logoColor=white)](https://colab.research.google.com/github/LocoreMind/LocoOperator/blob/main/LocoOperator_4B.ipynb)
[![ModelScope](https://img.shields.io/badge/ModelScope-624AFF?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMTAiIGZpbGw9IndoaXRlIi8+PC9zdmc+&logoColor=white)](https://modelscope.cn/organization/LocoreMind)

</div>

> **NextOrca** is the name of this fork and its coding-agent runtime. It extends the original **LocoOperator-4B** code-exploration model with a standalone provider-neutral runtime, hybrid local/cloud routing, persistent sessions, optional approval-gated edits, and a Claude Code-compatible proxy. The underlying LocoOperator-4B model and weights remain attributed to LocoreMind; the model links and original benchmark results below refer to that model, not to end-to-end NextOrca performance.

## 📋 Table of Contents

- 📰 [News & Updates](#-news--updates)
- 📝 [Introduction](#-introduction)
- ✨ [Key Features](#-key-features)
- 🏗️ [Architecture](#️-architecture)
- 📈 [Performance](#-performance)
- 🚀 [Quick Start](#-quick-start)
- 🔧 [Analysis Pipeline](#-analysis-pipeline)
- 📁 [Project Structure](#-project-structure)
- ⚠️ [Known Limitations](#️-known-limitations)
- 🧭 [Independent Agent Runtime](#independent-agent-runtime-experimental)
- 🔌 [MCP stdio Integrations](#mcp-stdio-integrations-experimental-linux-only)
- 🔀 [Hybrid Model Routing](#hybrid-model-routing-experimental)
- 📊 [Local Usage Metrics](#local-usage-and-routing-metrics)
- 🛠️ [Approved File Edits and Undo](#approved-file-edits-and-undo-experimental)
- 📄 [License](#-license)
- 🙏 [Acknowledgments](#-acknowledgments)

## 📰 News & Updates

- **\[2026-02-24\]** 🚀 LocoOperator-4B-GGUF released for local deployment.
- **\[2026-02-23\]** 🎉 LocoOperator-4B model card and evaluation analysis released.

## 📝 Introduction

NextOrca is a local-first coding-agent fork built around **LocoOperator-4B**, a tool-calling model trained via knowledge distillation from **Qwen3-Coder-Next** inference traces. The model specializes in multi-turn codebase exploration — reading files, searching code, and navigating project structures. NextOrca adds the runtime, provider adapters, session management, hybrid routing, and guarded file-edit workflow around that model.

<div align="center">

|  | LocoOperator-4B |
|:--|:--|
| **Base Model** | [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) |
| **Teacher Model** | Qwen3-Coder-Next |
| **Training Method** | Full-parameter SFT (distillation) |
| **Training Data** | 170,356 multi-turn conversation samples |
| **Max Sequence Length** | 16,384 tokens |
| **Training Hardware** | 4x NVIDIA H200 141GB SXM5 |
| **Training Time** | ~25 hours |
| **Framework** | MS-SWIFT |

</div>

## ✨ Key Features

- 🔧 **Tool-Calling Model**: LocoOperator-4B generates structured `<tool_call>` JSON for Read, Grep, Glob, Bash, Write, Edit, and Task. The NextOrca runtime exposes workspace-scoped Read/Grep/Glob by default; Write/Edit are opt-in and approval-gated, while Bash and Task execution are not enabled.
- 🎯 **100% JSON Validity**: Every tool call is valid JSON with all required arguments — outperforming the teacher model (87.6%)
- 🏠 **Local Deployment**: GGUF quantized, runs on Mac Studio via llama.cpp at zero API cost
- ⚡ **Lightweight Explorer**: 4B parameters, optimized for fast codebase search and navigation
- 🔄 **Multi-Turn**: Handles conversation depths of 3–33 messages with consistent tool-calling behavior

## 🏗️ Architecture

NextOrca supports both a standalone agent runtime and a hybrid setup in which LocoOperator-4B serves as a local **codebase explorer** alongside a stronger cloud model:

<div align="center">
  <img src="assets/architecture.png" width="80%" alt="Architecture" />
</div>

In hybrid mode, NextOrca routes repository exploration and explanation to the local model and sends implementation, debugging, tests, review, and planning tasks to the configured cloud model. Manual route overrides and a local-only privacy mode are available.

## 📈 Performance

Evaluated on 65 multi-turn conversation samples from diverse open-source projects (scipy, fastapi, arrow, attrs, gevent, gunicorn, etc.), with labels generated by Qwen3-Coder-Next.

### Core Metrics

<div align="center">

| Metric | Score |
|:-------|:-----:|
| **Tool Call Presence Alignment** | **100%** (65/65) |
| **First Tool Type Match** | **65.6%** (40/61) |
| **JSON Validity** | **100%** (76/76) |
| **Argument Syntax Correctness** | **100%** (76/76) |

</div>

The model perfectly learned *when* to use tools vs. when to respond with text (100% presence alignment). Tool type mismatches are between semantically similar tools (e.g. Grep vs Read) — different but often valid strategies.

### Tool Distribution Comparison

<div align="center">

| Tool | LocoOperator-4B | Qwen3-Coder-Next | Delta |
|:-----|:---------------:|:-----------------:|:-----:|
| Read | 22 | 32 | -10 |
| Bash | 22 | 17 | +5 |
| Grep | 14 | 18 | -4 |
| Glob | 9 | 11 | -2 |
| Task | 7 | 7 | 0 |
| Write | 2 | 3 | -1 |
| **Total** | **76** | **89** | **-13** |

</div>

### JSON & Argument Syntax Correctness

<div align="center">

| Model | JSON Valid | Argument Syntax Valid |
|:------|:---------:|:--------------------:|
| **LocoOperator-4B** | 76/76 (100%) | 76/76 (100%) |
| Qwen3-Coder-Next (teacher) | 89/89 (100%) | 78/89 (87.6%) |

</div>

> LocoOperator-4B achieves perfect structured output. The teacher model has 11 tool calls with missing required arguments (empty `arguments: {}`).

## 🚀 Quick Start

### Prerequisites

- **Claude Code** — `npm install -g @anthropic-ai/claude-code`
- **llama.cpp** — build from source or `brew install llama.cpp`
- **uv** — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **OpenRouter API key** — https://openrouter.ai/keys

### Serve with llama.cpp

```bash
# Download the GGUF model
# (replace with actual model path)

# Start the server
./llama-server \
    -m LocoOperator-4B.gguf \
    --ctx-size 51200 \
    --host 0.0.0.0 \
    --port 8080
```

### Recommended Settings

| Parameter | Value | Rationale |
|:----------|:------|:----------|
| Context size | 50K | Covers multi-turn exploration with room for tool outputs |
| Max turns | 10 | Sufficient for focused codebase exploration tasks |
| Temperature | 0.7 | Balanced between determinism and exploration |

## 🔧 Analysis Pipeline

This repo includes a hybrid analysis pipeline that combines LocoOperator-4B (local) with a cloud LLM via OpenRouter, orchestrated through `claude -p`.

```
claude -p (sonnet) ──→ proxy (9091) ──→ OpenRouter Qwen3-Coder-Next
  └─ subagent (haiku) ─→ proxy (9091) ──→ local llama-server (8080)
```

The main agent runs as sonnet (cloud), and when it spawns subagents (Task tool) they default to haiku, which the proxy routes to the local 4B model. If the local model hits context limits or exceeds 10 turns, the proxy automatically falls back to OpenRouter.

The proxy binds to loopback, requires the generated local bearer token for API requests, limits request size/concurrency, and streams remote responses incrementally. Local inference is currently non-streaming; local requests that require streaming are escalated to the cloud provider.

The proxy (`scripts/proxy.py`) handles:
- Anthropic Messages API ↔ OpenAI Chat Completions format conversion for the local model
- Parsing `<tool_call>` text output from the local model back into Anthropic tool_use blocks
- Automatic fallback to OpenRouter on context overflow

### Setup

```bash
# Clone the repository
git clone https://github.com/ahmedaisar/NextOrca.git
cd NextOrca

# Install Python dependencies
uv sync

# Configure your OpenRouter API key
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY
```

`.claude/settings.local.json` is generated locally on first run. The upstream `OPENROUTER_API_KEY` remains in `.env` and is never copied into Claude Code settings. Setup creates a separate random local proxy token and writes the token/settings with owner-only permissions. The analysis scripts run Claude Code in `plan` mode and save the returned stdout themselves.

Place your GGUF model at `models/LocoOperator-4B-GGUF/LocoOperator-4B.gguf`.

Place target projects under `data/repos/`.

### Single query test

```bash
./scripts/test_single.sh tqdm "How does tqdm detect if running in a Jupyter notebook?"
```

### Batch analyze

```bash
./scripts/analyze.sh tqdm
```

This reads queries from `data/queries/tqdm-queries.txt` and saves results to `data/outputs/tqdm/`.

### Adding More Projects

1. Clone a project into `data/repos/`:
   ```bash
   git clone --depth 1 https://github.com/user/repo data/repos/repo
   rm -rf data/repos/repo/.git
   ```
2. Create a queries file at `data/queries/repo-queries.txt` (tab-separated `id\tquery`)
3. Run: `./scripts/analyze.sh repo`

## Independent Agent Runtime (experimental)

The repository now includes an independent, read-only coding-agent runtime alongside the existing Claude Code compatibility proxy. It has a provider contract, a bounded model/tool loop, a JSON-schema-validated tool registry and workspace-scoped `Read`, `Glob` and literal-text `Grep` tools.

Install the project and development tools:

```bash
uv sync --extra dev
```

Run against a local OpenAI-compatible endpoint (for example, a llama.cpp server exposing `/v1/chat/completions`):

```bash
uv run nextorca \
  --base-url http://127.0.0.1:8080/v1 \
  --model your-local-model \
  --workspace ./data/repos/tqdm \
  "Explain how tqdm detects whether it is running in a Jupyter notebook."
```

Run against an OpenAI-compatible hosted endpoint such as OpenRouter:

```bash
export NEXTORCA_BASE_URL=https://openrouter.ai/api/v1
export NEXTORCA_API_KEY=your-key
export NEXTORCA_MODEL=your-provider/model
uv run nextorca --workspace ./data/repos/tqdm "Map the main package structure."
```

The runtime accepts `--base-url`, `--model`, `--api-key`, `--workspace` and `--max-turns`; `NEXTORCA_BASE_URL`, `NEXTORCA_API_KEY` and `NEXTORCA_MODEL` can supply defaults. Use `--verbose` to emit structured turn/tool events to stderr. Each run also prints a session ID to stderr; pass it back with `--session-id` to resume. The default SQLite database is `~/.nextorca/sessions.sqlite3` and can be changed with `--session-db` or `NEXTORCA_SESSION_DB`. Session files are written with owner-only database permissions. The runtime preserves system/user messages and recent turns; when the context budget is exceeded, it elides older tool output and assistant prose and records a `context_pruned` checkpoint. It errors rather than silently dropping required user/system context.

## MCP stdio integrations (experimental; Linux only)

NextOrca can connect to explicitly configured MCP stdio servers. MCP is disabled unless both a manifest and the \`--allow-mcp-tools\` flag are supplied. Commands are passed as an argv array (never through a shell), and every external tool invocation is marked as a mutation and requires interactive approval after NextOrca displays the server, tool name and arguments.

**MCP execution requires Linux and Bubblewrap.** Install Bubblewrap first:

\`\`\`bash
sudo apt-get install bubblewrap
\`\`\`

NextOrca fails closed when Bubblewrap is missing or on unsupported operating systems; it never falls back to running an MCP server directly on the host. The sandbox uses isolated Linux namespaces, drops Linux capabilities, exposes a minimal read-only system filesystem and mounts the configured workspace read-only. Network access is disabled by default. Set \`network_access: true\` only for a server you trust that needs network access.

Start from the example manifest and replace the sample command with the executable and server script you have installed:

\`\`\`bash
cp mcp-servers.example.json mcp-servers.json
# Edit command, cwd and any required environment-variable names.
uv run nextorca \\
  --workspace ./my-repo \\
  --mcp-config ./mcp-servers.json \\
  --allow-mcp-tools \\
  "Inspect this repository using the configured MCP tools."
\`\`\`

Each server entry supports:

- \`command\`: non-empty argv array; shell expansion and shell command strings are not supported.
- \`cwd\`: optional working directory within the workspace.
- \`env_passthrough\`: names of environment variables explicitly passed into the sandbox. Host API keys are not inherited by default. Dynamic-loader and interpreter injection variables are refused.
- \`network_access\`: defaults to \`false\`; \`true\` explicitly shares the host network namespace.
- \`writable_paths\`: existing, non-overlapping directories relative to the workspace that are bind-mounted writable. Leave this empty for read-only access.

MCP server instructions, tool descriptions and tool results are untrusted data and cannot override NextOrca's policy. The MCP process is terminated on request timeout and when the CLI exits. The sandbox limits filesystem visibility and network reachability, but it is not a full virtual machine: only run server commands you trust. Writable paths are a broad grant to that server; writes made directly by an MCP process do not pass through NextOrca's file diff/checkpoint undo mechanism. Cross-platform sandbox backends, resource quotas, and stronger integration tests remain future work. MCP integrations are experimental and are not a commercial-deployment security guarantee.

## Hybrid Model Routing (experimental)

The CLI can use both a local OpenAI-compatible model endpoint and a cloud OpenAI-compatible provider. In automatic mode, NextOrca routes repository exploration and code explanation locally, while edits, debugging, tests, reviews and planning use the cloud model. The router emits a structured decision reason when `--verbose` is enabled.

```bash
export NEXTORCA_LOCAL_BASE_URL=http://127.0.0.1:8080/v1
export NEXTORCA_LOCAL_MODEL=your-local-tool-calling-model

export NEXTORCA_CLOUD_BASE_URL=https://openrouter.ai/api/v1
export NEXTORCA_CLOUD_MODEL=qwen/qwen3-coder-next
export OPENROUTER_API_KEY=your-key

uv run nextorca --route-mode auto --workspace ./my-repo \
  "Map the main package structure."

uv run nextorca --route-mode auto --verbose --workspace ./my-repo \
  "Refactor the retry logic and add tests."
```

Routing controls:

- `--route-mode auto`: route retrieval/explanation to local and more demanding coding tasks to cloud; temporarily unavailable local inference can escalate to cloud.
- `--route-mode local`: force local inference.
- `--route-mode cloud`: force the configured cloud provider.
- `--privacy-mode local-only`: never send prompts/tool context to a cloud provider; use with `--route-mode local` or `auto`.
- `--route-mode single`: preserve the original one-provider behavior and `--base-url`/`--model` options.

Set `NEXTORCA_LOCAL_BASE_URL`, `NEXTORCA_LOCAL_MODEL`, `NEXTORCA_CLOUD_BASE_URL`, `NEXTORCA_CLOUD_MODEL`, `NEXTORCA_LOCAL_API_KEY` and `NEXTORCA_CLOUD_API_KEY` to persist provider settings. `OPENROUTER_API_KEY` is accepted as a cloud-key fallback. The router currently uses a deterministic request classifier, not learned confidence scoring; its decisions are visible and manually overridable. The versioned classification corpus is checked in at `evals/routing_cases.json` and evaluated by `uv run python evals/evaluate_routing.py --fail-under 0.95`.

### Local usage and routing metrics

Each model attempt records latency, normalized input/output token usage, success/failure, provider/model and the routing decision in the local SQLite session database. Nothing is sent to an analytics service. View the workspace totals, or narrow the report to one resumed session:

```bash
uv run nextorca --workspace ./my-repo --session-stats
uv run nextorca --workspace ./my-repo --session-id SESSION_ID --session-stats
```

Provider token counts are reported when the endpoint supplies usage metadata. Cost is intentionally not estimated yet because provider pricing and account-specific discounts need an explicit price configuration; token counts are not a substitute for billing data.

## Approved File Edits and Undo (experimental)

The independent runtime remains read-only by default. To enable file creation and exact-text edits, pass `--allow-edits`. The agent will prepare a unified diff and ask for explicit interactive approval before changing a file. Shell execution is still unavailable.

```bash
# Opt in to approved file edits
uv run nextorca --allow-edits --workspace ./my-repo "Update the version string in pyproject.toml"

# List saved checkpoints for this workspace
uv run nextorca --workspace ./my-repo --list-checkpoints

# Undo one approved change (only if the file still matches the checkpoint)
uv run nextorca --workspace ./my-repo --undo-checkpoint CHECKPOINT_ID
```

Every approved mutation creates a checkpoint in the local SQLite session database. The tool output returns its checkpoint ID. Undo refuses if the target file has changed since the checkpoint, so newer work is not overwritten. The `--allow-edits` option exposes only `Write` and `Edit`; it does not enable Bash, arbitrary commands, or unrestricted filesystem access.

**Current boundary:** the independent runtime is an experimental preview. Its built-in tools are workspace-confined; unknown tool names and invalid arguments are rejected; execution defaults to a read-only permission policy. File mutations are opt-in through `--allow-edits`, require interactive diff approval and create reversible local checkpoints. It currently uses non-streaming OpenAI Chat Completions-compatible requests and does not include a general-purpose shell sandbox, MCP extensions or a GUI. The existing hybrid proxy remains available for integrating the LocoOperator-4B explorer model with Claude Code.

## 📁 Project Structure

```
NextOrca/
├── .env.example                         # OpenRouter key template
├── pyproject.toml
├── models/LocoOperator-4B-GGUF/
│   └── LocoOperator-4B.gguf
├── examples/                            # model inference examples
│   ├── quick_start.py
│   └── codebase_analysis_example.py
├── data/
│   ├── repos/                           # target projects to analyze
│   ├── queries/tqdm-queries.txt         # analysis queries (tab-separated: id\tquery)
│   └── outputs/                         # analysis results
├── prompts/
│   └── analyze_query.txt                # prompt template
└── scripts/
    ├── proxy.py                         # hybrid routing proxy
    ├── setup.sh                         # auto-generates .claude/settings.local.json
    ├── start_services.sh                # auto-starts llama-server + proxy
    ├── analyze.sh                       # batch analysis runner
    └── test_single.sh                   # single query test
```

## Training Details

<details>
  <summary>📋 Click to expand full training configuration</summary>

| Parameter | Value |
|:----------|:------|
| Base model | Qwen3-4B-Instruct-2507 |
| Teacher model | Qwen3-Coder-Next |
| Method | Full-parameter SFT |
| Training data | 170,356 samples |
| Hardware | 4x NVIDIA H200 141GB SXM5 |
| Parallelism | DDP (no DeepSpeed) |
| Precision | BF16 |
| Epochs | 1 |
| Batch size | 2/GPU, gradient accumulation 4 (effective batch 32) |
| Learning rate | 2e-5, warmup ratio 0.03 |
| Max sequence length | 16,384 tokens |
| Template | qwen3_nothinking |
| Framework | MS-SWIFT |
| Training time | ~25 hours |
| Checkpoint | Step 2524 |

</details>

## ⚠️ Known Limitations

- First-tool-type match is 65.6% — the model sometimes picks a different (but not necessarily wrong) tool than the teacher
- Tends to under-generate parallel tool calls compared to the teacher (76 vs 89 total calls across 65 samples)
- Preference for Bash over Read may indicate the model defaults to shell commands where file reads would be more appropriate
- Evaluated on 65 samples only; larger-scale evaluation needed

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- 🤖 **[Qwen Team](https://huggingface.co/Qwen)** for the Qwen3-4B-Instruct-2507 base model
- 🛠️ **[MS-SWIFT](https://github.com/modelscope/ms-swift)** for the training framework
- 🦙 **[llama.cpp](https://github.com/ggerganov/llama.cpp)** for efficient local inference
- 🤖 **[Anthropic](https://www.anthropic.com/)** for the Claude Code agent loop design that inspired this work
