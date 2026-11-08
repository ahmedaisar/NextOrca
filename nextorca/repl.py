from __future__ import annotations

import sys

from nextorca.goals import GoalRunner
from nextorca.runtime import AgentRuntime

HELP = """NextOrca interactive commands:
  /help       Show this help
  /session    Show the current session ID
  /new        Start a fresh conversation
  /tools      List available tools
  /context    Show session context size and last compaction
  /compact    Summarize older conversation history for future turns
  /mcp        List configured MCP tools
  /plugins    List loaded plugin tools
  /goal       /goal <objective> [--verify <command>]
              /goal status | resume | clear
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
        if prompt == "/tools":
            print("\n".join(runtime.tools.names) or "No tools registered.")
            continue
        if prompt == "/context":
            state = runtime.context_status()
            if state is None:
                print("No persistent session context yet.")
            else:
                compacted = state["last_compaction"]
                detail = (
                    f", last compacted through message {compacted['through_message_count']}"
                    if compacted
                    else ", not compacted yet"
                )
                print(
                    f"{state['message_count']} stored messages, "
                    f"{state['message_chars']} transcript characters{detail}."
                )
            continue
        if prompt == "/compact":
            try:
                result = runtime.compact()
                print(
                    f"Saved a {len(result['summary'])}-character summary of "
                    f"{result['through_message_count']} messages. Original transcript remains in SQLite."
                )
                print(result["summary"][:800])
            except (OSError, ValueError, RuntimeError) as exc:
                print(f"\nnextorca compact: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if prompt == "/mcp":
            names = [name for name in runtime.tools.names if name.startswith("mcp_")]
            print("\n".join(names) or "No MCP tools loaded. Start with --allow-mcp-tools.")
            continue
        if prompt == "/plugins":
            names = [name for name in runtime.tools.names if name.startswith("plugin_")]
            print("\n".join(names) or "No plugin tools loaded.")
            continue
        if prompt == "/goal" or prompt.startswith("/goal "):
            runner = GoalRunner(runtime)
            argument = prompt[len("/goal"):].strip()
            if argument == "status":
                state = runner.status()
                if state is None:
                    print("No goal recorded in this session.")
                else:
                    print(f"{state.get('status')}: {state.get('objective')} (attempt {state.get('iteration', 0)})")
                continue
            if argument == "resume":
                print(runner.resume())
                continue
            if argument == "clear":
                runner.clear()
                print("Goal state cleared.")
                continue
            objective, separator, verify = argument.partition(" --verify ")
            if not objective:
                print("Usage: /goal <objective> [--verify <command>]")
                continue
            try:
                print(runner.run(objective, verify_command=verify.strip() if separator else None))
            except (OSError, ValueError, RuntimeError) as exc:
                print(f"\nnextorca goal: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if prompt.startswith("/"):
            print(f"Unknown command: {prompt.split()[0]}. Type /help.")
            continue

        try:
            answer = runtime.run(prompt)
            if runtime.last_session_id:
                runtime.session_id = runtime.last_session_id
                print(f"\n[{runtime.last_session_id}]")
            if runtime.last_turn_streamed:
                print()
            elif answer:
                print(f"\n{answer}")
        except KeyboardInterrupt:
            print("\nRequest interrupted. The saved session can be continued.")
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"\nnextorca: {type(exc).__name__}: {exc}", file=sys.stderr)
