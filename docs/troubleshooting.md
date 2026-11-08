# Troubleshooting

## Provider connection errors

- Confirm the API base URL includes the provider's OpenAI-compatible path, commonly /v1.
- Check the model identifier expected by the server.
- For hosted providers, set NEXTORCA_CLOUD_API_KEY or NEXTORCA_API_KEY as appropriate.
- Try a one-shot prompt to separate provider connectivity from REPL behavior.
- Use --verbose to inspect structured provider and route events without printing credentials.

## Interactive terminal behavior

- Launch without a positional prompt to enter the REPL. Non-interactive stdin requires a one-shot prompt.
- Ctrl-C interrupts the current request; Ctrl-D exits.
- Use /session to copy the current session ID. Resume it with --session-id ID.
- Use /tools, /mcp and /plugins to see which tools are available.

## File edits and shell commands

- Every interactive file mutation displays a diff and asks for approval.
- Shell and plugin commands run with your OS user permissions after approval. Review the exact command and working directory.
- One-shot mode is read-only by default. Prefer the interactive REPL for changes.
- If a command times out, run a narrower command or increase its tool timeout where supported.

## Skills

- Put each skill in a folder containing a file named SKILL.md.
- Ensure frontmatter has a lowercase name and one-line description, and the name matches the directory.
- Check startup warnings for malformed, oversized or duplicate skills.

## Plugins

- Put plugin folders in .nextorca/plugins or ~/.nextorca/plugins.
- Check plugin.json syntax and schema_version 1.
- Plugin tool commands are argv arrays. Required arguments must be referenced by a complete {argument} token.
- Plugin commands are not sandboxed; only install plugins you trust.

## MCP

- MCP currently requires Linux and Bubblewrap. If sandbox initialization fails, NextOrca fails closed; do not disable host user-namespace restrictions as a workaround.
- Configure a command that exists in the sandbox PATH and only grant the writable paths/network access the server needs.
- Use /mcp to see registered tools.

## Goal mode and context

- /goal status shows the last saved goal state; /goal resume continues active or paused work.
- Goal verification commands require approval. If review fails, the worker receives feedback and retries up to the configured limit.
- /context reports transcript size; /compact writes a summary event without deleting the original SQLite transcript.
- Compaction is lossy summarization. Review the saved summary if an important detail appears missing.
