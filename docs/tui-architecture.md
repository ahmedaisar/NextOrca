# NextOrca terminal UI architecture decision

**Status:** accepted for Plan 005  
**Date:** 2026-11-12

## Decision

Use **prompt_toolkit 3.0.53+ (before 4.0)** as the terminal presentation/input layer. Keep the existing AgentRuntime, provider/router, tool registry, SQLite store and permission semantics as the authorities. The TUI is a view and input adapter around one existing runtime instance; it must not implement another agent loop.

The default interactive selector is --ui auto, which opens the full-screen terminal UI when its dependency is available. --ui tui requires the TUI and emits an actionable setup error if it cannot load. --ui repl explicitly selects the existing line-oriented REPL.

## Alternatives considered

| Approach | Benefits | Costs / limitations | Decision |
|---|---|---|---|
| Hand-written ANSI / standard-library terminal loop | No runtime dependency; complete control over output | Must implement terminal modes, keyboard decoding, resize, Windows console differences, input editing, mouse/selection, Unicode widths and restoration. High risk for a feature whose purpose is a good terminal interaction model | Rejected |
| Rich + standard input | Strong text rendering, tables, panels and live display primitives | Does not by itself provide the full-screen event loop, editor focus model, key binding stack and approval/input multiplexing needed here; would still require a second terminal framework | Rejected |
| prompt_toolkit | Full-screen Application, layout/widgets, Emacs/Vi key bindings, mouse, input editing, Unicode handling, Windows support, testable input/output abstractions and alternate-screen handling | Adds a modest pure-Python dependency and requires UI code to respect its event loop and redraw contract | **Selected** |

## Runtime and thread ownership

- AgentRuntime.run() remains the only path to execute a user turn. The TUI attaches an event handler to the existing runtime; assistant stream deltas and tool lifecycle events are rendered in the transcript.
- Provider selection and HybridRouter remain in CLI/runtime assembly. The TUI reads the configured route/privacy state but does not pick a provider.
- SQLite remains behind SQLiteSessionStore. Session list/resume uses Plan 006 APIs; view code does not write SQL.
- The TUI approval broker implements the existing PermissionPolicy interface. Read-only tools remain automatic. Every mutation requires a preview and an explicit one-time Y/N decision. Missing previews, timeout, Ctrl-C denial and UI shutdown all fail closed.
- The agent worker runs off the terminal event loop so streamed events can repaint the UI. Prompt-toolkit's documented thread-safe Application.invalidate() is the only cross-thread UI signal. The UI refuses to exit while a turn is running, preventing a detached worker from continuing after the operator believes the app has stopped.
- Terminal mode / alternate-screen cleanup is delegated to Application.run(); an application exception exits the full-screen context before it is presented to the operator.

## Interaction contract

- The full-screen view shows current workspace, model/route/privacy, session identity, conversation, stream output, tool activity, and approval previews.
- Commands /help, /session, /sessions, /resume, /new, /tools, /route, /privacy, /context, /compact, /mcp, /plugins, /goal, and /exit remain available.
- Ctrl-Q exits only while idle. Ctrl-C and Esc deny a pending approval; Ctrl-C does not detach active work. --ui repl retains the previous interface for recovery and scripting workflows.
- One-shot invocations remain non-interactive and read-only by default; TUI mode is only selected for an interactive TTY.

## References

- [prompt_toolkit 3.0 PyPI release](https://pypi.org/project/prompt_toolkit/) (3.0.53, released 2026-07-26).
- [Full-screen applications](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/full_screen_apps.html).
- [Application reference](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/reference.html) (alternate screen, Application.invalidate() thread-safety, input/output injection and terminal size polling).
