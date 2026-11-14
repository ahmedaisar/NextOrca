# Coding-task benchmark

NextOrca's coding-task benchmark complements the existing routing-classifier evaluator. The routing evaluator measures task classification accuracy; this harness measures whether a configured provider and route can complete small, reproducible repository tasks and pass their verification tests.

## Quick, offline smoke run

The default mode is deterministic and offline. It does not construct a network-backed provider:

```bash
uv run python -m evals.run_benchmark --smoke
```

Run the complete six-task fake-provider corpus locally:

```bash
uv run python -m evals.run_benchmark
```

The smoke command is intended for lightweight PR CI. The complete fake corpus is useful for local harness development and is opt-in in the test suite:

```bash
NEXTORCA_FULL_BENCHMARK_TESTS=1 uv run pytest tests/test_evaluation_fixtures.py tests/test_evaluation_runner.py -q
```

## Live provider runs

Real providers are never constructed unless `--live` is explicitly supplied. A single-provider run uses the same adapter registry as the CLI:

```bash
export NEXTORCA_PROVIDER_ADAPTER=openai-compatible
export NEXTORCA_BASE_URL=https://your-provider.example/v1
export NEXTORCA_API_KEY=...
export NEXTORCA_MODEL=your-model

uv run python -m evals.run_benchmark --live --route-mode single
```

For Anthropic and Gemini, use `NEXTORCA_PROVIDER_ADAPTER=anthropic` with `ANTHROPIC_API_KEY`, or `NEXTORCA_PROVIDER_ADAPTER=gemini` with `GEMINI_API_KEY`. Provider-specific keys are read from the environment; they are never written to reports.

Hybrid routing reads the normal NextOrca variables:

- `NEXTORCA_LOCAL_PROVIDER_ADAPTER`, `NEXTORCA_LOCAL_BASE_URL` (defaults to `http://127.0.0.1:8080/v1`), `NEXTORCA_LOCAL_MODEL`, `NEXTORCA_LOCAL_API_KEY`
- `NEXTORCA_CLOUD_PROVIDER_ADAPTER`, `NEXTORCA_CLOUD_BASE_URL`, `NEXTORCA_CLOUD_MODEL`, `NEXTORCA_CLOUD_API_KEY`

Then choose `--route-mode auto`, `--route-mode local`, or `--route-mode cloud`. The report records the actual route decision when the router emits one.

Select tasks with repeatable `--task TASK_ID` options. Use `--manifest PATH` to supply a separately validated task corpus. Verification is deliberately restricted to explicit `python -m pytest -q` argv arrays; shell strings are not accepted.

## Task contract and isolation

The versioned manifest is `evals/benchmark_tasks.json`. Each task specifies its category, fixture directory, prompt, allowed tools, verification argv, timeout, turn/tool-call limits, expected baseline exit code, and optional read-only policy.

Every run copies its fixture into a fresh temporary directory. The model sees only the task's bounded `read_file`, `list_files`, `write_file` (when allowed), and fixed `run_verification` tools. The verification tool can run only the manifest's pre-approved pytest argv; it cannot accept shell commands. Paths are resolved under that temporary workspace; parent traversal and symlink escapes are rejected. Each task first runs its expected baseline verification, then the agent, then verification again. A baseline mismatch is reported rather than scored as a provider failure.

On POSIX, the overall task deadline interrupts the runtime with an interval timer; verification subprocesses have their own timeout and are killed as a process group. On Windows, verification subprocesses are killed on timeout and the runtime deadline is checked at runtime boundaries; provider transports should also enforce request timeouts.

## Reports and privacy

Reports are written locally to `benchmark-results/summary.json` and `benchmark-results/runs.json` by default. Override the location with `--output-dir`.

Reports include the corpus and source revision, provider/adapter and model identifiers, route decision, task outcome, verification status, elapsed time, tool/model call counts, changed paths, and provider-reported token usage. Missing usage remains `null`; NextOrca does not estimate cost or fabricate token counts.

By default reports do **not** include task prompts, model transcripts, environment variables, API keys, or captured command output. Benchmark results are not uploaded. Do not publish reports from private repositories without reviewing the task metadata and changed paths first.

The fixture corpus is intentionally small and synthetic. Scores are not a general leaderboard: compare configurations on the same corpus revision, repeat live runs, and consider variance before changing routing defaults.
