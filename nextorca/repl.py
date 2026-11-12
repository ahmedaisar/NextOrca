from __future__ import annotations

import sys

from nextorca.goals import GoalRunner
from nextorca.routing import HybridRouter
from nextorca.runtime import AgentRuntime

HELP = """NextOrca interactive commands:
  /help       Show this help
  /session    Show the current session ID
  /sessions   List recent sessions in this workspace
  /resume     /resume <session-id-or-index>
  /new        Start a fresh conversation
  /tools      List available tools
  /route      Show or set auto/local/cloud routing
  /privacy    Show or set balanced/local-only privacy
  /context    Show session context size and last compaction
  /compact    Summarize older conversation history for future turns
  /mcp        List configured MCP tools
  /plugins    List loaded plugin tools
  /goal       /goal <objective> [--verify <command>]
              /goal status | resume | clear
  /exit       Leave NextOrca

Type a request in natural language to work on the current project.
Ctrl-C interrupts the current request; Ctrl-D exits."""




def _available_sessions(runtime: AgentRuntime) -> list[dict]:
    if runtime.session_store is None or runtime.workspace_root is None:
        return []
    return runtime.session_store.list_sessions(runtime.workspace_root, limit=20)


def _resume_session(runtime: AgentRuntime, selection: str) -> str:
    if runtime.session_store is None or runtime.workspace_root is None:
        raise ValueError("Session resume requires persistent sessions.")
    metadata = runtime.session_store.get_session(selection)
    if metadata is not None:
        if metadata["workspace"] != runtime.workspace_root:
            raise ValueError("Session is no longer available in this workspace.")
        session_id = selection
    else:
        sessions = _available_sessions(runtime)
        selected = None
        if selection.isdigit():
            index = int(selection)
            if 1 <= index <= len(sessions):
                selected = sessions[index - 1]
        if selected is None:
            raise ValueError("No session matched that ID or list index.")
        session_id = selected["session_id"]
        metadata = runtime.session_store.get_session(session_id)
        if metadata is None or metadata["workspace"] != runtime.workspace_root:
            raise ValueError("Session is no longer available in this workspace.")
    runtime.session_id = session_id
    runtime.last_session_id = session_id
    return session_id


def run_repl(runtime: AgentRuntime) -> None:
    """Run a persistent terminal conversation over the normal agent runtime."""
    if isinstance(runtime.provider, HybridRouter):
        profile = (
            f"hybrid/{runtime.provider.route_mode} · {runtime.provider.privacy_mode} · "
            f"local={runtime.provider.local_model or 'off'} · "
            f"cloud={runtime.provider.cloud_model or 'off'}"
        )
    else:
        profile = runtime.model
    print(
        f"NextOrca · {profile} · workspace {runtime.workspace_root or 'current'}"
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
        if prompt == "/sessions":
            sessions = _available_sessions(runtime)
            if not sessions:
                print("No saved sessions for this workspace.")
            else:
                for index, session in enumerate(sessions, start=1):
                    preview = session.get("last_user_prompt") or "(no user prompt yet)"
                    if session.get("preview_truncated"):
                        preview += "…"
                    print(
                        f"{index}. {session['session_id']} · {session['model']} · "
                        f"{session['message_count']} messages · {preview}"
                    )
            continue
        if prompt.startswith("/resume "):
            selection = prompt[len("/resume "):].strip()
            if not selection:
                print("Usage: /resume <session-id-or-index>")
                continue
            try:
                session_id = _resume_session(runtime, selection)
                print(f"Resuming session {session_id}.")
            except (OSError, ValueError, RuntimeError) as exc:
                print(f"\nnextorca resume: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if prompt == "/tools":
            print("\n".join(runtime.tools.names) or "No tools registered.")
            continue
        if prompt == "/route" or prompt.startswith("/route "):
            if not isinstance(runtime.provider, HybridRouter):
                print("This session uses one provider. Restart with --route-mode auto to enable hybrid routing.")
                continue
            argument = prompt[len("/route"):].strip()
            if not argument or argument == "status":
                print(
                    f"{runtime.provider.route_mode} routing; "
                    f"local={runtime.provider.local_model or 'off'}, "
                    f"cloud={runtime.provider.cloud_model or 'off'}."
                )
                continue
            if argument not in {"auto", "local", "cloud"}:
                print("Usage: /route [auto|local|cloud]")
                continue
            if argument == "local" and runtime.provider.local_provider is None:
                print("No local provider is configured.")
                continue
            if argument == "cloud" and runtime.provider.cloud_provider is None:
                print("No cloud provider is configured.")
                continue
            if argument == "cloud" and runtime.provider.privacy_mode == "local-only":
                print("Cloud routing is blocked by local-only privacy mode.")
                continue
            runtime.provider.route_mode = argument
            print(f"Routing set to {argument}.")
            continue
        if prompt == "/privacy" or prompt.startswith("/privacy "):
            if not isinstance(runtime.provider, HybridRouter):
                print("Privacy routing controls require hybrid mode.")
                continue
            argument = prompt[len("/privacy"):].strip()
            if not argument or argument == "status":
                print(f"Privacy mode: {runtime.provider.privacy_mode}.")
                continue
            if argument not in {"balanced", "local-only"}:
                print("Usage: /privacy [balanced|local-only]")
                continue
            if argument == "local-only" and runtime.provider.local_provider is None:
                print("Local-only mode requires a configured local provider.")
                continue
            if argument == "local-only" and runtime.provider.route_mode == "cloud":
                print("Set /route auto or /route local before enabling local-only privacy.")
                continue
            runtime.provider.privacy_mode = argument
            print(f"Privacy mode set to {argument}.")
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
