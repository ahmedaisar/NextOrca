# Plan 003: Reject non-finite MCP numeric arguments

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. Keep this as a separate PR from workspace changes.

> **Drift check (run first)**: `git diff --stat f207d19..HEAD -- nextorca/mcp_stdio.py tests/test_mcp_schema_validation.py`. If either in-scope file changed since this plan was written, compare the current validator to the excerpt below before proceeding.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `f207d19`, 2026-11-12

## Why this matters

MCP tool arguments are validated against schemas advertised by an external server. The numeric validator checks Python types and minimum/maximum constraints, but it does not reject NaN or positive/negative infinity. Python's standard JSON decoder accepts these non-standard constants by default, and comparisons involving NaN are false, so a value can bypass both range checks. Reject non-finite floats before applying numeric bounds so the MCP client enforces a predictable finite-number contract.

## Current state

- `nextorca/mcp_stdio.py:120-147` contains `_validate_remote_value`.
- The `number` type check at lines 130–132 accepts any Python `int` or `float`, excluding booleans.
- Numeric bounds at lines 142–146 compare the value to `minimum` and `maximum`. There is no finite-value check before those comparisons.
- The validator is recursive and is reached for nested object properties and array items.
- Existing validator test style appears in `tests/test_mcp_stdio.py:260-273`, where a nested MCP schema is used to verify rejection of an out-of-range integer. For pure schema validation, prefer a new test module so tests can run without constructing `MCPStdioClient` or Bubblewrap.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install | `uv sync --extra dev` | Exit 0 |
| Focused tests | `uv run pytest tests/test_mcp_schema_validation.py -q` | All focused tests pass without Bubblewrap |
| Full tests | `uv run pytest` | Exit 0 |
| Lint | `uv run ruff check nextorca tests evals examples` | Exit 0 |
| Compile | `uv run python -m compileall -q nextorca examples evals` | Exit 0 |

## Scope

**In scope**
- `nextorca/mcp_stdio.py`
- `tests/test_mcp_schema_validation.py` (new)

**Out of scope**
- MCP process startup/termination and Bubblewrap configuration.
- JSON parsing policy for unrelated application configuration.
- Provider request serialization or public CLI behavior.

## Git workflow

- Branch: `fix/finite-mcp-numbers`
- Keep the validator change and focused tests in one PR.
- Do not add a dependency; use the Python standard library.

## Steps

### Step 1: Add pure validator tests

Create `tests/test_mcp_schema_validation.py` and exercise `_validate_remote_arguments` or the narrowest appropriate private validation boundary directly. Cover NaN, positive infinity, and negative infinity for a `number` field, both at the root and nested under an object/array. Include finite integers and finite floats at valid minimum/maximum boundaries to prove normal values remain accepted.

**Verify**: `uv run pytest tests/test_mcp_schema_validation.py -q` → non-finite cases fail with `ToolExecutionError`; finite boundary cases pass.

### Step 2: Enforce finite floats

In `_validate_remote_value`, reject non-finite floats before range comparisons. Use `math.isfinite` only for float values so arbitrarily large Python integers are not converted to float as part of the check. Preserve the existing boolean exclusion and numeric minimum/maximum behavior.

**Verify**: `uv run pytest tests/test_mcp_schema_validation.py tests/test_mcp_stdio.py -q` → pure validator regressions pass; sandbox-dependent tests run or skip according to their runtime prerequisite.

## Test plan

- Reject `float("nan")`, `float("inf")`, and `float("-inf")`.
- Verify the rejection applies recursively to nested object properties and array items.
- Accept finite integer and float values within schema boundaries.
- Preserve existing minimum/maximum errors for finite out-of-range values.
- Ensure booleans are not accepted as numbers.

## Done criteria

- [ ] Non-finite floats are rejected before numeric range comparisons.
- [ ] Finite boundary values and existing integer validation retain their behavior.
- [ ] Pure validation tests run without Bubblewrap.
- [ ] `uv run pytest` exits 0.
- [ ] `uv run ruff check nextorca tests evals examples` exits 0.
- [ ] No files outside the scope list are modified.

## STOP conditions

Stop and report if:
- The real provider/runtime contract intentionally requires NaN or infinity (no such requirement was found in the audited code).
- Correct validation requires a change to protocol parsing or provider serialization outside the scope list.
- A new third-party dependency appears necessary.

## Maintenance notes

Keep validation recursive. When adding new numeric schema keywords or numeric data types, preserve the finite-value check before range comparisons. Keep these pure validation tests outside the sandbox-gated MCP integration module so they continue to run in fast CI.
