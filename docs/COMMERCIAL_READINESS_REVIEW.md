# NextOrca: Personal Coding Agent Roadmap

**Project:** NextOrca  
**Baseline:** main @ a9b19e15f7e9ebc64b91367035b5b98f4d308401  
**Review date:** 2026-11-08  
**Purpose:** Build a capable, native-feeling terminal coding agent for the maintainer's own projects. This is a product direction and implementation plan, not a commercial-readiness assessment.
**Implementation status:** Phase 1 (native terminal agent) and Phase 2 (Agent Skills) are merged. Phase 3 (local plugins) is merged. Phase 4 (goal mode and MCP terminal UX) is merged. Phase 5 (provider streaming and context compaction) is merged. Phase 6 (seamless local/cloud orchestration) is in review.

## Product direction

NextOrca should feel like an AI coding agent that lives in the terminal. A user starts it in a repository, describes work in natural language, watches it inspect and modify the code, sees commands and tool activity, approves consequential actions, and can resume the conversation later.

The primary experience is the coding agent itself. Local/cloud orchestration remains an internal capability: the same tools, sessions, permissions, skills and commands should work regardless of which model handles a turn. Users should not have to think about separate local and cloud applications.

### Product principles

1. **Terminal first.** Interactive REPL, clear tool activity, readable output, keyboard interruption and useful slash commands.
2. **Actually do the work.** Read and search source, edit files, run tests/builds/git and iterate based on real command output.
3. **Human control without friction.** Show shell commands and risky actions before execution; do not claim an action succeeded until the tool confirms it.
4. **Familiar extension formats.** Load Agent Skills using the SKILL.md format and support project/user skills; expose plugins and MCP as explicit, inspectable extensions.
5. **Sessions that survive.** Resume work, compact long histories without losing critical state, and make the current task/session visible.
6. **Goal-oriented completion.** For longer tasks, verify with actual commands and an independent review rather than relying on the worker's self-assessment.
7. **Local first, cloud when useful.** Preserve local/cloud providers and hybrid routing behind the same agent loop; respect local-only mode.
8. **Personal-project scope.** No SSO, SCIM, billing, enterprise admin, support SLAs, centralized analytics, or other SaaS obligations unless the maintainer later wants them.

## Baseline assessment

The repository already has a useful foundation:

- Independent provider-neutral agent loop and typed tool registry.
- OpenAI Chat Completions-compatible provider.
- Local/cloud routing and local-only privacy mode.
- Workspace Read/Glob/Grep and approval-gated Write/Edit operations.
- SQLite sessions, checkpoints and local model metrics.
- Experimental MCP stdio discovery and Linux Bubblewrap sandbox.
- CI for Ruff, compile checks, shell syntax, CLI help, routing corpus and pytest.

The most important gaps for the intended product are not enterprise controls. They are everyday coding-agent ergonomics and capabilities:

- No interactive terminal session; CLI currently requires one prompt and exits.
- No shell/terminal tool, so the agent cannot run tests, linters, builds or git commands.
- No first-class skills discovery/activation.
- No plugin packaging/installation/enable-disable lifecycle.
- No native provider streaming or clear interactive progress experience.
- No goal mode with verification and independent reviewer.
- Context handling prunes old outputs but does not perform a deliberate summary/compaction workflow.
- MCP exists but needs to fit naturally into the interactive experience and skill/plugin configuration.
- Hybrid routing is deterministic but not surfaced as a seamless per-turn decision in a long-running session.
- README still describes the tool as a read-only-by-default runtime rather than an interactive coding agent.
- Historical research assets and notebook content should be reviewed for relevance and removed if they no longer belong to the product.

## Implementation phases

Each phase is a separate sequential pull request. A phase is merged only after its focused tests and the repository CI pass. The next phase starts from the merged result.

### Phase 1 — Native terminal coding agent

**Goal:** Make NextOrca usable as an everyday interactive coding agent.

- Start an interactive REPL when invoked without a prompt.
- Keep a single persistent runtime/session across turns.
- Add /help, /session, /new, /exit; support Ctrl-C/Ctrl-D cleanly.
- Add a shell tool for tests, builds, git and project commands, scoped to the project working directory and guarded by exact-command approval.
- Enable focused Write/Edit in interactive mode with diff approval.
- Show concise tool activity and clear completion/error output.
- Preserve one-shot mode for scripts and automation; keep it non-interactive and safe by default.

**Acceptance:** A user can launch in a repo, ask the agent to inspect code, approve an edit, approve a test command, iterate on failures, and continue the same session. Tests cover REPL commands, shell preview/approval, timeout/output bounds and one-shot safety.

### Phase 2 — Agent Skills

**Goal:** Load standard skills without inventing a proprietary format.

- Discover project and user skills in documented locations: .agents/skills/, .claude/skills/, .nextorca/skills/, and ~/.nextorca/skills/.
- Parse each SKILL.md frontmatter; require valid name/description and reject path traversal.
- Add only skill name/description to the initial system context; load full instructions only when selected by the model.
- Add an explicit LoadSkill tool, bounded file size and clear source/path attribution.
- Resolve duplicate names deterministically and report malformed skills without preventing startup.
- Document authoring and example skills.

**Acceptance:** Existing compatible Agent Skills can be copied into a supported folder and discovered; a selected skill's instructions become available to the model; malformed or escaping skill paths are rejected.

### Phase 3 — Plugin system
**Goal:** Support installable, manageable local extensions without allowing plugins to bypass the tool policy.

- Define a small versioned plugin manifest.
- Support plugins bundling skills, prompt guidance and declarative tool definitions initially.
- Load plugins from project and user directories; support list/inspect/enable/disable.
- Validate manifest schemas, paths, names, size limits and duplicate identifiers.
- Route all plugin tools through the same registry, argument validation and permission policy.
- Defer arbitrary Python plugin execution and lifecycle hooks until there is a compelling use case and an isolation design.

**Acceptance:** A sample plugin can be enabled in a project, its skills/tools appear in the agent, disabled plugins expose nothing, malformed manifests fail closed, and plugin tools cannot bypass approval.

### Phase 4 — Native MCP and useful agent workflows

**Goal:** Make integrations and longer tasks feel native.

- Integrate MCP discovery, status and tool visibility into the interactive session.
- Keep explicit per-call approval, visible server/tool identity and bounded output.
- Add clean startup/shutdown and recoverable connection failures.
- Add goal mode with objective, max turns and optional verify command.
- A goal is complete only after verification passes and an independent reviewer checks the result.
- Persist goal state so a session can resume an interrupted goal.
- Keep subagents bounded and optional; do not make them a prerequisite for the main agent.

**Acceptance:** User can inspect configured MCP servers, approve an individual call, run a goal with a verify command, interrupt/resume it, and see why completion was accepted or rejected.

### Phase 5 — Long-session context and provider streaming

**Goal:** Make longer interactive work reliable and responsive.

- Add provider streaming to the normalized provider contract.
- Render incremental assistant output and tool progress in the terminal.
- Add explicit /context and /compact commands.
- Compact using a structured summary that preserves objective, decisions, changed files, tests run, outstanding work and user constraints.
- Keep transcript history append-only or versioned so compaction never silently corrupts provider protocol state.
- Add cancellation semantics that stop active provider/tool work and leave the session resumable.

**Acceptance:** Long sessions compact predictably, retain essential task state, stream output, and recover cleanly from Ctrl-C/provider errors.

### Phase 6 — Seamless local/cloud orchestration

**Goal:** Keep orchestration behind one agent interface.

- Make provider profiles configurable without requiring CLI flag changes for every session.
- Preserve local, cloud, auto and local-only modes.
- Allow the router to choose per turn while tools, session and permissions remain unchanged.
- Make route decisions visible in concise status output and explain why escalation occurred.
- Never escalate in local-only mode; make cloud fallback opt-in and explicit.
- Add tests for provider outage, cloud fallback, route override and session continuity across provider changes.

**Acceptance:** A user can stay in one interactive session while NextOrca routes local/cloud turns; the session history and tool behavior remain coherent, and local-only mode never sends context to cloud.

### Phase 7 — Product polish and distribution

**Goal:** Make it pleasant to install, learn and use on personal projects.

- Update README around the terminal-first experience.
- Add install/run/upgrade commands and a configuration example.
- Add sample skills and a sample plugin.
- Add practical troubleshooting and provider setup guides.
- Clean up historical notebooks/assets only after confirming they are no longer referenced.
- Add end-to-end scripted fake-provider tests and a small repeatable coding-task evaluation.
- Keep CI fast and focused on the product's supported environments.

**Acceptance:** A new user can install NextOrca, configure a local or cloud endpoint, launch an interactive session, add a skill/plugin, and complete a small coding task by following the docs.

## Explicitly out of scope for now

- Enterprise readiness, SSO/SCIM, RBAC, billing, quotas and organization admin.
- Centralized telemetry, hosted control plane or multi-tenant deployment.
- Commercial SLAs, release compliance programs and formal certification.
- Full-screen TUI before the REPL/tool loop is excellent.
- Arbitrary third-party Python plugin execution.
- Complex autonomous parallel-agent orchestration before goal mode and verification work well.

## Definition of “feels like a native coding agent”

A typical session should look like:

    $ nextorca
    NextOrca · local-model · ~/src/my-project
    > Find the bug causing the login test to fail and fix it.
      Read src/auth/session.py
      Grep refresh_token
      Shell (approval required): uv run pytest tests/auth -q
      Edit src/auth/session.py (diff approval)
      Shell (approval required): uv run pytest tests/auth -q
    Fixed the refresh-token expiry check. Tests: 18 passed.
    Session: 2e...
    > /exit

The exact UI can evolve, but the user should be able to ask, observe, approve, interrupt, resume and verify without leaving the terminal.

## Reference

- mini-harness: https://github.com/phuryn/mini-harness — a useful reference for the terminal loop, skills, MCP, permissions, sessions, compaction and goal verification. NextOrca keeps its own provider abstraction and local/cloud orchestration.
