# Plan 012: Add opt-in PostgreSQL and Vercel Blob persistence

> **Executor instructions**: Add cloud persistence as an opt-in extension while preserving local SQLite as the default. Vercel does not itself provide a first-party relational database in the way the old Vercel Postgres product name implies; databases are provisioned through Marketplace integrations (for example, Neon or Supabase) and expose a PostgreSQL connection URL. Use Vercel Blob for object/artifact storage, not as a transactional database or live SQLite file system. Verify current official SDK/API contracts before implementation.
>
> **Drift check (run first)**: `git diff --stat bbba47f..HEAD -- nextorca/session_store.py nextorca/context.py nextorca/cli.py pyproject.toml tests docs`. If any listed path changed, reconcile the current schema and persistence interfaces before proceeding.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `bbba47f45689f9edfeb7d1beb100b6e95acca93a`, 2026-11-14

## Why this matters

NextOrca currently stores sessions, events, checkpoints and project memory in a local SQLite database. That is appropriate for a local-first CLI, but it cannot synchronize state across machines or preserve selected artifacts independently of a workstation. An opt-in PostgreSQL backend, using a database installed through Vercel Marketplace, can provide transactional shared metadata; Vercel Blob can store larger immutable artifacts and benchmark reports. SQLite must remain the zero-configuration default, and cloud storage must be explicit because it transfers private conversation and project data off-device.

## Current state

- `nextorca/session_store.py` defines `SQLiteSessionStore`, creates tables for sessions, messages, events, checkpoints and project memory, and uses SQLite transactions and foreign keys.
- `nextorca/cli.py` constructs `SQLiteSessionStore` for the active workspace. The current CLI does not select a remote persistence backend.
- Session text is redacted before display using local redaction helpers, but redaction for display is not a sufficient guarantee for cloud persistence; the new backend must apply a documented data-minimization policy before upload.
- `pyproject.toml` has no PostgreSQL or Vercel Blob dependency. Keep database and Blob libraries optional.
- Vercel Marketplace supports connecting third-party database integrations to projects. The application receives provider environment variables such as a PostgreSQL connection URL; database lifecycle and billing remain with the selected Marketplace provider.
- Vercel documentation describes a Python Blob module imported as `from vercel import blob`; verify current package/API version and access-control options before using it.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Tests | `uv run pytest -q` | All tests pass |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |
| CLI smoke | `uv run nextorca --help` | Exit 0 |

## Suggested executor toolkit

- Vercel Marketplace storage overview: https://vercel.com/docs/storage.
- Vercel Blob Python SDK: https://vercel.com/docs/vercel-blob/python-sdk-reference.
- PostgreSQL database integration through Vercel Marketplace: https://vercel.com/docs/storage/vercel-postgres (verify current redirects and product status; do not assume the retired Vercel Postgres product is still a first-party database).
- Use a PostgreSQL driver compatible with the existing synchronous store API, unless the implementation deliberately introduces and tests an async boundary.

## Scope

**In scope**
- A persistence protocol or narrow store factory so the CLI can select SQLite (default) or PostgreSQL (opt-in).
- A PostgreSQL implementation for session metadata, messages, events, checkpoints and project memory, with migrations and transactional semantics.
- Optional Vercel Blob support for immutable artifacts such as benchmark reports, exported session archives and approved patch bundles.
- CLI configuration and documentation for database URL, Blob token, privacy/retention and provider setup.
- Tests for SQLite compatibility, PostgreSQL schema/transaction behavior, Blob metadata/ACL handling and failure recovery.

**Out of scope**
- Replacing SQLite as the default.
- Automatically uploading all local session history or project memory.
- Using Vercel Blob as a database, SQLite network filesystem or live transactional event store.
- Automatically provisioning a Marketplace database, accepting provider terms, or incurring charges.
- Selecting Neon vs Supabase without an explicit maintainer decision; use the standard PostgreSQL wire protocol.
- Storing API keys, OAuth tokens, environment variables or raw provider credentials in session records or Blob objects.
- Cross-user multi-tenant SaaS, billing, auth server or a hosted NextOrca web service.

## Steps

### Step 1: Define persistence boundaries and data export policy

Map every table and public method in `SQLiteSessionStore`; define which methods must be supported by the backend protocol. Separate transactional records from large immutable artifacts. Define opt-in upload behavior, workspace scoping, user identity/namespace, retention, deletion and export semantics. Default cloud sync to off. Require explicit confirmation before a first upload and before enabling synchronization for a workspace.

Do not silently upload prior SQLite records. Provide an explicit export/import or one-time migration command with dry-run counts, redaction preview and confirmation. Ensure project memory source provenance and workspace boundaries remain intact.

**Verify**: add contract tests that run against SQLite and a fake backend; verify all store methods used by runtime/CLI are enumerated and cloud sync is disabled by default.

### Step 2: Add PostgreSQL store using a standard PostgreSQL connection

Use a synchronous PostgreSQL driver compatible with current store methods. Read the database URL from an environment variable (e.g. `DATABASE_URL`) and never write it to config, logs or session events. Implement migrations with explicit schema version tracking, parameterized SQL, transactions, foreign keys, unique constraints and indexes matching the SQLite access patterns. Use workspace/user namespace scoping for every read/write; do not assume a shared database means all sessions belong to one user.

Keep the SQLite implementation intact. Do not rewrite it into a cross-database SQL abstraction unless a narrow repository interface proves sufficient. Avoid silent fallback from PostgreSQL to SQLite on connection errors; surface a clear error to prevent writes appearing in a different store.

**Verify**: unit tests cover SQL translation/migration ordering using a fake connection; an opt-in local integration test uses `NEXTORCA_POSTGRES_TEST_URL` and a disposable test schema/database, validates migrations, CRUD, transaction rollback, foreign-key behavior, concurrent writes and namespace isolation. It is skipped without the flag.

### Step 3: Add Vercel Blob as an artifact store only

Verify the current Python Blob SDK and whether private Blob access, content type, metadata, deletion and bounded downloads are supported. Implement an artifact interface for immutable report/archive/patch objects. Require an explicit token and configured store; enforce content-size bounds, stable object keys scoped to the workspace, retention/deletion, and non-public access unless the operator deliberately chooses public access. Use signed or authenticated access where supported. Do not upload raw transcripts by default.

**Verify**: fake Blob client tests cover upload/download metadata, private access, object-key scoping, size limits, deletion and failure handling. Live Blob tests require `NEXTORCA_VERCEL_BLOB_INTEGRATION=1` and credentials; they are never run in PR CI.

### Step 4: Add explicit CLI backend selection and one-time migration

Add explicit storage selection such as `--session-store sqlite|postgres` or environment configuration, with SQLite default. Add an explicit migration/export command that displays source and destination, record counts, redaction policy and estimated upload volume before confirmation. Require interactive confirmation or an explicit confirmation flag for non-interactive migration. Do not automatically sync or merge divergent local and cloud histories.

**Verify**: CLI tests cover SQLite default, missing DATABASE_URL, Postgres connection failure without fallback, cloud consent, migration dry-run and explicit confirmation.

### Step 5: Document Vercel Marketplace setup and privacy implications

Document that the user must provision/connect a PostgreSQL Marketplace integration in the Vercel project and supply its connection URL to NextOrca; NextOrca does not create the database or accept Marketplace billing terms. Document Blob setup and private access, region/latency, retention, backup, deletion and data transfer. Clarify that cloud session storage includes private prompts, tool outputs and project metadata unless excluded by policy.

**Verify**: docs name the actual provider integration and environment variables implemented; `uv run nextorca --help` exits 0; no secret values appear in examples.

## Test plan

- Store contract tests shared by SQLite, PostgreSQL and fake implementations.
- Migration tests from a representative SQLite schema to PostgreSQL, including duplicate IDs, partial failures and retry safety.
- Workspace namespace isolation and transaction rollback tests.
- Blob adapter tests for private/public access modes, upload size, content metadata, deletion and error mapping.
- Tests prove default SQLite mode makes no outbound request and cloud mode never silently falls back.
- Optional live PostgreSQL and Blob integration tests are explicitly gated and excluded from CI.

## Done criteria

- [ ] SQLite remains the default and behaves unchanged.
- [ ] PostgreSQL is opt-in and uses standard PostgreSQL connectivity from a Vercel Marketplace database integration.
- [ ] All session, event, checkpoint and project-memory methods used by runtime are covered by the store contract.
- [ ] Workspace/user namespace isolation and transactional behavior are tested.
- [ ] Cloud upload/sync is off by default and requires explicit consent.
- [ ] Vercel Blob stores only bounded immutable artifacts, never the live SQLite database.
- [ ] No silent fallback between SQLite and PostgreSQL occurs.
- [ ] No credentials or raw environment values are persisted or logged.
- [ ] Optional live integration tests are gated; PR CI remains network-free.
- [ ] `uv run ruff check nextorca tests evals examples`, compileall, `uv run pytest -q` and CLI help exit 0.

## STOP conditions

Stop and report if:
- The existing SQLite store exposes methods that cannot be represented safely by the proposed persistence contract without a broad runtime rewrite.
- PostgreSQL schema changes cannot preserve transactionality, ordering or workspace isolation.
- Vercel Blob's current Python SDK cannot guarantee the required private-access or deletion behavior.
- The Marketplace provider requires a vendor-specific SQL dialect or unsupported billing/account action.
- Cloud sync cannot avoid uploading secrets, raw credentials or unredacted transcripts by default.

## Maintenance notes

Treat PostgreSQL as a generic database provider, not a Vercel-owned database product. Vercel Marketplace provisions and connects third-party services; users own the provider account, billing and backups. Keep Blob object retention and database retention distinct. Future encryption-at-rest/client-side encryption and multi-device conflict resolution are separate designs and must not be implied by this plan.
