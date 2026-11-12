# Project memory

NextOrca project memory is a small, local SQLite store for facts, commands, conventions and decisions that an operator explicitly chooses to keep across sessions. It is separate from the append-only session transcript and from per-session context compaction.

## Safety and scope

- Every record is created by an explicit `memory add` command. The agent does not extract or persist memories automatically.
- Every record is scoped to the canonical workspace path and must cite a user-authored message sequence from a session in that same workspace.
- Records carry a type, source session ID, source message sequence, created/updated timestamps and `operator_confirmed` status.
- The store reuses the existing owner-only SQLite session database (0600 file permissions on POSIX); there is no remote database, embedding API, scheduler or background reflection.
- Content is limited to 2,000 characters. The first version caps each workspace at 2,000 records. Common credential forms are rejected on save.
- Memory is enabled by default for a workspace after the operator has added records. `memory off` stops retrieval/injection but keeps records for later inspection or re-enable.
- `memory forget` physically deletes the selected row. No vector index or other derived search representation is kept.
- Retrieval is deterministic lexical overlap, capped at four records and 1,000 characters per record, with a 6,000-character total context ceiling. The provider request includes each selected record's ID and provenance.
- Memory is local at rest, but selected records are included in the current model prompt. In balanced routing, that prompt may go to the configured cloud provider. Use `--privacy-mode local-only` when prompts and selected memory must remain on the local model, or `memory off` to suppress memory injection.
- Stored memory is reference data, not instructions. It may be stale and cannot override the system policy or current user request.

## Add a memory

First locate the source user message in a saved session. The sessions search result includes the source message sequence:

```bash
nextorca sessions search "the project decision you want to preserve" --workspace .
```

Then explicitly save a concise record with that session ID and sequence:

```bash
nextorca memory add "Redis cache keys include the schema version and expire after five minutes." \
  --type decision \
  --source-session YOUR_SESSION_ID \
  --source-message 2 \
  --workspace .
```

Supported types: `decision`, `command`, `fact`, and `convention`.

## Manage memories

```bash
nextorca memory status --workspace .
nextorca memory list --workspace .
nextorca memory show MEMORY_ID --workspace .
nextorca memory search "Redis cache keys" --workspace .
nextorca memory off --workspace .
nextorca memory on --workspace .
nextorca memory forget MEMORY_ID --workspace .
```

The `search` output shows the records that would currently be selected for a matching prompt, including match terms and provenance. These commands use the configured session database and do not start a model provider.

In the interactive terminal, the same operations are available with `/memory status|list|show|search|preview|add|forget|on|off`. For example:

```text
/memory add decision YOUR_SESSION_ID 2 "Redis cache keys include the schema version."
/memory preview Redis cache keys
/memory off
/memory on
```

## Evaluation and limitations

The current retrieval system is intentionally small and explainable. Its test corpus covers workspace isolation, source provenance, explicit creation, deletion, disablement, credential rejection, lexical matching, context limits and no-persistence of injected context. It is not semantic search and does not infer new facts. Revisit embeddings or reflection only if this deterministic version demonstrably misses recurring project knowledge.
