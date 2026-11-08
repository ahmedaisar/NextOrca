from __future__ import annotations

import sys

from nextorca.runtime import AgentRuntime

HELP = """NextOrca interactive commands:
  /help       Show this help
  /session    Show the current session ID
  /new        Start a fresh conversation
  /exit       Leave NextOrca

Type a request in natural language to work on the current project.
Ctrl-C interrupts the current request; Ctrl-D exits."""


def run_repl(runtime: AgentRuntime) -> None:
    """Run a persistent terminal conversation over the normal agent runtime."""
    print(
        f"NextOrca · {runtime.model} · workspace {runtime.workspace_root or 'current'}"
        "\nType /help for commands. File edits and shell commands ask before running."
    )
    while True:
        try:
            prompt = input("\n› ").strip()
        except EOFError:
            print()
            return
        except KeyboardInterrupt:
            print("\n(Use Ctrl-D or /exit to quit.)")
            continue

        if not prompt:
            continue
        if prompt in {"/exit", "/quit"}:
            return
        if prompt == "/help":
            print(HELP)
            continue
        if prompt == "/session":
            print(runtime.session_id or runtime.last_session_id or "No session yet.")
            continue
        if prompt == "/new":
            runtime.session_id = None
            runtime.last_session_id = None
            print("Started a new conversation on the next prompt.")
            continue
        if prompt.startswith("/"):
            print(f"Unknown command: {prompt.split()[0]}. Type /help.")
            continue

        try:
            answer = runtime.run(prompt)
            if runtime.last_session_id:
                runtime.session_id = runtime.last_session_id
                print(f"\n[{runtime.last_session_id}]")
            if answer:
                print(f"\n{answer}")
        except KeyboardInterrupt:
            print("\nRequest interrupted. The saved session can be continued.")
        except Exception as exc:
            print(f"\nnextorca: {type(exc).__name__}: {exc}", file=sys.stderr)
