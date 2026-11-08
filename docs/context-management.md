# Context Management

The interactive terminal exposes two commands:

- /context — show the stored message count, transcript size and last compaction point.
- /compact — ask the configured provider to summarize the session.

The summary prompt preserves the current objective, user constraints, key decisions, changed/inspected files, commands and test results actually observed, remaining work and blockers. The summary is saved in the append-only session event log.

The original messages are never rewritten or deleted. On subsequent turns, NextOrca constructs provider context from the original system message, the latest compaction summary, and recent complete conversation turns. If a recent tool response belongs to an assistant tool call, the pair is kept together so provider message structure remains valid.

Compaction uses the same configured provider/router and therefore respects local-only mode. It is not an archival export or a lossless transcript format; inspect the summary when exact historical detail matters.
