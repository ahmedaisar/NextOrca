# Goal Mode

Goal mode is an interactive workflow for multi-step tasks.

## Start a goal

    /goal Fix the login refresh bug and add a regression test --verify uv run pytest tests/auth -q

The optional text after --verify is executed as a shell command from the project root. NextOrca displays the exact command and asks for approval before running it. Keep the command focused and deterministic.

## Completion protocol

1. The worker uses the normal tools and calls GoalDone only when it believes implementation is complete.
2. If a verification command was provided, NextOrca runs it through the same approved Shell tool. A non-zero exit or timeout fails verification.
3. A fresh reviewer runtime is created with a separate session and read-only workspace tools, including GitDiff.
4. The reviewer must end with exactly VERDICT: APPROVE or VERDICT: REVISE. Missing or revise verdicts fail closed.
5. Failed verification/review feedback is returned to the worker for another attempt. The default limit is five attempts.

The reviewer is a model-based second opinion, not a formal proof or a guarantee that every bug is found. Always inspect important changes yourself.

## Session commands

- /goal status — show the last saved goal state.
- /goal resume — continue an active or paused goal from its saved objective and feedback.
- /goal clear — mark the saved goal state cleared.

Goal state is persisted as append-only session events. If the process exits during a run, the latest active state can be resumed. Worker and reviewer conversations are stored as separate sessions.

## MCP and extension visibility

- /mcp lists registered MCP tools.
- /plugins lists registered local plugin tools.
- /tools lists all tools exposed to the current agent.

MCP calls still require per-call approval. Start configured MCP servers with --allow-mcp-tools and --mcp-config. Plugin commands use their own per-call approval path.
