from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.data_structures import Point
from prompt_toolkit.layout import Dimension, HSplit, Layout, ScrollOffsets, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea

from nextorca.goals import GoalRunner
from nextorca.routing import HybridRouter
from nextorca.runtime import AgentRuntime
from nextorca.tool_registry import ToolSpec

HELP = """NextOrca terminal workspace

Enter            Send a message
Ctrl-Q           Quit when the agent is idle
Ctrl-C           Deny a pending approval; otherwise quit when idle
F1               Show this help

Commands:
  /help
  /session
  /sessions
  /resume <session-id-or-index>
  /new
  /tools
  /route [status|auto|local|cloud]
  /privacy [status|balanced|local-only]
  /context
  /compact
  /mcp
  /plugins
  /goal <objective> [--verify <command>]
  /goal status | resume | clear
  /exit
"""

APPROVAL_TIMEOUT_SECONDS = 300
MAX_TRANSCRIPT_MESSAGES = 250


@dataclass
class _PendingApproval:
    tool_name: str
    preview: str
    resolved: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class TerminalApprovalPolicy:
    """Interactive approval broker for the full-screen terminal UI.

    Read-only tools remain automatic. Mutations require a preview and an
    explicit y/n decision from the foreground UI. A timeout always denies.
    """

    def __init__(self, *, timeout_seconds: float = APPROVAL_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._pending: _PendingApproval | None = None
        self._closed = False
        self._invalidate: Callable[[], None] = lambda: None

    def attach(self, invalidate: Callable[[], None]) -> None:
        self._invalidate = invalidate

    @property
    def pending(self) -> _PendingApproval | None:
        with self._lock:
            return self._pending

    def is_pending(self) -> bool:
        return self.pending is not None

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self.resolve(False)

    def resolve(self, approved: bool) -> bool:
        with self._lock:
            pending = self._pending
            if pending is None:
                return False
            pending.approved = approved
            pending.resolved.set()
        self._invalidate()
        return True

    def authorize(
        self,
        tool: ToolSpec,
        arguments: dict[str, Any],
        *,
        preview: str | None = None,
    ) -> bool:
        del arguments
        if tool.read_only:
            return True
        if not preview:
            return False

        pending = _PendingApproval(tool_name=tool.name, preview=preview)
        with self._lock:
            if self._closed or self._pending is not None:
                return False
            self._pending = pending

        self._invalidate()
        resolved = pending.resolved.wait(self.timeout_seconds)
        with self._lock:
            if self._pending is pending:
                self._pending = None
        self._invalidate()
        return bool(resolved and pending.approved)


class TerminalWorkspace:
    """Prompt-toolkit view over the existing AgentRuntime and session store."""

    def __init__(
        self,
        runtime: AgentRuntime,
        approval: TerminalApprovalPolicy,
        *,
        input: Any | None = None,
        output: Any | None = None,
    ) -> None:
        self.runtime = runtime
        self.approval = approval
        self._lock = threading.RLock()
        self._messages: list[tuple[str, str]] = []
        self._partial = ""
        self._busy = False
        self._status = "Ready"
        self._notice = ""
        self._route_note = ""
        self._previous_event_handler = runtime.on_event

        self.input = TextArea(
            height=1,
            prompt="› ",
            multiline=False,
            wrap_lines=False,
            focus_on_click=True,
            accept_handler=self._accept_input,
            read_only=Condition(self._input_locked),
        )
        self._approval_window = Window(
            content=FormattedTextControl(self._approval_fragments),
            height=Dimension(min=0, max=9),
            wrap_lines=True,
            always_hide_cursor=True,
        )
        self._application = self._build_application(input=input, output=output)
        self.approval.attach(self._application.invalidate)
        runtime.on_event = self._handle_event

    @property
    def application(self) -> Application[Any]:
        return self._application

    def _profile(self) -> str:
        if isinstance(self.runtime.provider, HybridRouter):
            return (
                f"{self.runtime.provider.route_mode}/{self.runtime.provider.privacy_mode} "
                f"· local {self.runtime.provider.local_model or 'off'} "
                f"· cloud {self.runtime.provider.cloud_model or 'off'}"
            )
        return self.runtime.model

    def _header(self) -> FormattedText:
        workspace = Path(self.runtime.workspace_root or ".").name or "."
        session = self.runtime.session_id or self.runtime.last_session_id or "new"
        return FormattedText(
            [
                ("class:header", " NextOrca "),
                ("class:muted", f" {workspace} · {self._profile()} · session {session[:12]}"),
            ]
        )

    def _transcript_fragments(self) -> FormattedText:
        with self._lock:
            messages = list(self._messages[-MAX_TRANSCRIPT_MESSAGES:])
            partial = self._partial
            busy = self._busy

        fragments: list[tuple[str, str]] = []
        for role, text in messages:
            style = {
                "user": "class:user",
                "assistant": "class:assistant",
                "tool": "class:tool",
                "system": "class:muted",
                "error": "class:error",
            }.get(role, "")
            prefix = {
                "user": "You  ",
                "assistant": "NextOrca  ",
                "tool": "Tool  ",
                "system": "Info  ",
                "error": "Error  ",
            }.get(role, "")
            fragments.append((style, f"{prefix}{text}\n"))
            fragments.append(("", "\n"))

        if partial:
            fragments.append(("class:assistant", f"NextOrca  {partial}"))
        elif busy:
            fragments.append(("class:muted", "NextOrca is working…"))
        if not fragments:
            fragments.append(
                ("class:muted", "Ask NextOrca to inspect, change, and verify this workspace.\n")
            )
        return FormattedText(fragments)

    def _approval_fragments(self) -> FormattedText:
        pending = self.approval.pending
        if pending is None:
            return FormattedText([])
        preview = pending.preview
        if len(preview) > 6_000:
            preview = preview[:6_000] + "\n[approval preview truncated in the UI]"
        return FormattedText(
            [
                ("class:approval", f" APPROVAL REQUIRED · {pending.tool_name} · [Y] approve once  [N] deny\n"),
                ("class:muted", preview),
            ]
        )

    def _footer(self) -> FormattedText:
        with self._lock:
            status = self._status
            notice = self._notice
            busy = self._busy
        pending = self.approval.is_pending()
        if pending:
            status = "Approval needed · Y approve once / N deny"
        elif busy:
            status = f"Working · {status} · Ctrl-C does not detach a running operation"
        elif notice:
            status = notice
        else:
            status = f"{status} · Enter send · F1 help · Ctrl-Q quit"
        return FormattedText([("class:footer", f" {status} ")])

    def _build_application(self, *, input: Any | None, output: Any | None) -> Application[Any]:
        keys = KeyBindings()

        @keys.add("c-q")
        def _(event: Any) -> None:
            if self._is_busy():
                self._set_notice("Wait for the current turn to finish before quitting.")
                return
            event.app.exit(result=0)

        @keys.add("c-c")
        def _(event: Any) -> None:
            if self.approval.resolve(False):
                self._set_notice("Approval denied.")
                return
            if self._is_busy():
                self._set_notice("The current turn is still running; wait for it to finish.")
                return
            event.app.exit(result=0)

        @keys.add("c-d")
        def _(event: Any) -> None:
            if self._is_busy():
                self._set_notice("The current turn is still running; wait for it to finish.")
                return
            event.app.exit(result=0)

        @keys.add("y", filter=Condition(self.approval.is_pending))
        def _(event: Any) -> None:
            self.approval.resolve(True)
            self._set_notice("Approved once.")

        @keys.add("n", filter=Condition(self.approval.is_pending))
        def _(event: Any) -> None:
            self.approval.resolve(False)
            self._set_notice("Approval denied.")

        @keys.add("escape", filter=Condition(self.approval.is_pending))
        def _(event: Any) -> None:
            self.approval.resolve(False)
            self._set_notice("Approval denied.")

        @keys.add("f1")
        def _(event: Any) -> None:
            self._append_message("system", HELP)

        root = HSplit(
            [
                Window(content=FormattedTextControl(self._header), height=1),
                Window(
                    content=FormattedTextControl(
                        self._transcript_fragments,
                        get_cursor_position=self._transcript_cursor,
                    ),
                    height=Dimension(weight=1, min=3),
                    wrap_lines=True,
                    always_hide_cursor=True,
                    scroll_offsets=ScrollOffsets(top=1, bottom=1),
                ),
                self._approval_window,
                Frame(self.input, title="Message"),
                Window(content=FormattedTextControl(self._footer), height=1),
            ]
        )
        return Application(
            layout=Layout(root, focused_element=self.input),
            key_bindings=keys,
            style=Style.from_dict(
                {
                    "header": "bold bg:#243447 #ffffff",
                    "footer": "bg:#243447 #ffffff",
                    "user": "bold #5fb3ff",
                    "assistant": "#d8dee9",
                    "tool": "#b48ead",
                    "muted": "#888888",
                    "error": "bold #ff6b6b",
                    "approval": "bold #ffcc66",
                }
            ),
            full_screen=True,
            mouse_support=True,
            erase_when_done=False,
            input=input,
            output=output,
        )

    def _is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def _input_locked(self) -> bool:
        return self._is_busy() or self.approval.is_pending()

    def _transcript_cursor(self) -> Point:
        with self._lock:
            line_count = sum(text.count("\\n") for _role, text in self._messages)
            line_count += self._partial.count("\\n")
        return Point(x=0, y=max(0, line_count))

    def _set_notice(self, message: str) -> None:
        with self._lock:
            self._notice = message
            self._status = message
        self._application.invalidate()

    def _append_message(self, role: str, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._messages.append((role, text))
            self._notice = ""
        self._application.invalidate()

    def _handle_event(self, event: Any) -> None:
        if self._previous_event_handler is not None:
            self._previous_event_handler(event)
        with self._lock:
            if event.type == "assistant_delta":
                self._partial += str(event.data.get("content", ""))
                self._status = "Receiving response"
            elif event.type == "model_turn_started":
                self._status = f"Model turn {event.data.get('turn', '')}"
            elif event.type == "tool_started":
                self._messages.append(("tool", f"Started {event.data.get('tool', 'tool')}"))
                self._status = "Running tool"
            elif event.type == "tool_completed":
                self._messages.append(
                    ("tool", f"Completed {event.data.get('tool', 'tool')} "
                     f"({event.data.get('output_chars', 0)} chars)")
                )
            elif event.type == "tool_denied":
                self._messages.append(("system", f"Denied {event.data.get('tool', 'tool')}"))
            elif event.type == "tool_error":
                self._messages.append(("error", f"{event.data.get('tool', 'tool')}: {event.data.get('error', 'error')}"))
        self._application.invalidate()

    def _accept_input(self, buffer: Any) -> bool:
        prompt = buffer.text.strip()
        if not prompt:
            return True
        if self.approval.is_pending():
            self._set_notice("Approve or deny the pending operation with Y or N.")
            return True
        self._handle_prompt(prompt)
        return True

    def _handle_prompt(self, prompt: str) -> None:
        if prompt in {"/exit", "/quit"}:
            if self._is_busy():
                self._set_notice("Wait for the current turn to finish before quitting.")
                return
            self.application.exit(result=0)
            return
        if prompt == "/help":
            self._append_message("system", HELP)
            return
        if prompt == "/session":
            self._append_message(
                "system",
                self.runtime.session_id or self.runtime.last_session_id or "No session yet.",
            )
            return
        if prompt == "/new":
            if self._is_busy():
                self._set_notice("Cannot switch sessions while a turn is running.")
                return
            self.runtime.session_id = None
            self.runtime.last_session_id = None
            self._append_message("system", "Started a new session.")
            return
        if prompt == "/sessions":
            self._show_sessions()
            return
        if prompt.startswith("/resume "):
            self._resume(prompt[len("/resume "):].strip())
            return
        if prompt == "/tools":
            self._append_message("system", "\n".join(self.runtime.tools.names) or "No tools registered.")
            return
        if prompt == "/mcp":
            names = [name for name in self.runtime.tools.names if name.startswith("mcp_")]
            self._append_message("system", "\n".join(names) or "No MCP tools loaded.")
            return
        if prompt == "/plugins":
            names = [name for name in self.runtime.tools.names if name.startswith("plugin_")]
            self._append_message("system", "\n".join(names) or "No plugin tools loaded.")
            return
        if prompt.startswith("/route"):
            self._route_command(prompt[len("/route"):].strip())
            return
        if prompt.startswith("/privacy"):
            self._privacy_command(prompt[len("/privacy"):].strip())
            return
        if prompt == "/context":
            state = self.runtime.context_status()
            self._append_message("system", "No persistent session context yet." if state is None else str(state))
            return
        if prompt == "/compact":
            self._start_worker(prompt, lambda: self.runtime.compact()["summary"])
            return
        if prompt == "/goal" or prompt.startswith("/goal "):
            self._goal_command(prompt[len("/goal"):].strip())
            return
        if prompt.startswith("/"):
            self._append_message("error", f"Unknown command: {prompt.split()[0]}. Type /help.")
            return
        self._start_worker(prompt, lambda: self.runtime.run(prompt), user_prompt=prompt)

    def _show_sessions(self) -> None:
        store = self.runtime.session_store
        workspace = self.runtime.workspace_root
        if store is None or workspace is None:
            self._append_message("system", "Persistent sessions are not configured.")
            return
        sessions = store.list_sessions(workspace, limit=20)
        if not sessions:
            self._append_message("system", "No saved sessions for this workspace.")
            return
        lines = []
        for index, item in enumerate(sessions, start=1):
            preview = item.get("last_user_prompt") or "(no user prompt yet)"
            if item.get("preview_truncated"):
                preview += "…"
            lines.append(
                f"{index}. {item['session_id']} · {item['message_count']} messages · {preview}"
            )
        self._append_message("system", "\n".join(lines))

    def _resume(self, selection: str) -> None:
        if self._is_busy():
            self._set_notice("Cannot switch sessions while a turn is running.")
            return
        store = self.runtime.session_store
        workspace = self.runtime.workspace_root
        if store is None or workspace is None or not selection:
            self._append_message("error", "Usage: /resume <session-id-or-index>")
            return
        metadata = store.get_session(selection)
        if metadata is not None and metadata["workspace"] != workspace:
            self._append_message("error", "Session is not available in this workspace.")
            return
        if metadata is not None:
            session_id = selection
        elif selection.isdigit():
            sessions = store.list_sessions(workspace, limit=20)
            index = int(selection)
            if index < 1 or index > len(sessions):
                self._append_message("error", "No session matched that ID or list index.")
                return
            session_id = sessions[index - 1]["session_id"]
        else:
            self._append_message("error", "No session matched that ID or list index.")
            return
        metadata = store.get_session(session_id)
        if metadata is None or metadata["workspace"] != workspace:
            self._append_message("error", "Session is not available in this workspace.")
            return
        self.runtime.session_id = session_id
        self.runtime.last_session_id = session_id
        self._append_message("system", f"Resuming session {session_id}.")

    def _route_command(self, argument: str) -> None:
        provider = self.runtime.provider
        if not isinstance(provider, HybridRouter):
            self._append_message("system", "This session uses one provider. Restart with --route-mode auto to enable hybrid routing.")
            return
        if not argument or argument == "status":
            self._append_message("system", f"{provider.route_mode}; local={provider.local_model or 'off'}; cloud={provider.cloud_model or 'off'}")
            return
        if argument not in {"auto", "local", "cloud"}:
            self._append_message("error", "Usage: /route [auto|local|cloud]")
            return
        if argument == "local" and provider.local_provider is None:
            self._append_message("error", "No local provider is configured.")
            return
        if argument == "cloud" and provider.cloud_provider is None:
            self._append_message("error", "No cloud provider is configured.")
            return
        if argument == "cloud" and provider.privacy_mode == "local-only":
            self._append_message("error", "Cloud routing is blocked by local-only privacy mode.")
            return
        provider.route_mode = argument
        self._append_message("system", f"Routing set to {argument}.")

    def _privacy_command(self, argument: str) -> None:
        provider = self.runtime.provider
        if not isinstance(provider, HybridRouter):
            self._append_message("system", "Privacy routing controls require hybrid mode.")
            return
        if not argument or argument == "status":
            self._append_message("system", f"Privacy mode: {provider.privacy_mode}.")
            return
        if argument not in {"balanced", "local-only"}:
            self._append_message("error", "Usage: /privacy [balanced|local-only]")
            return
        if argument == "local-only" and provider.local_provider is None:
            self._append_message("error", "Local-only mode requires a configured local provider.")
            return
        if argument == "local-only" and provider.route_mode == "cloud":
            self._append_message("error", "Set /route auto or /route local before enabling local-only privacy.")
            return
        provider.privacy_mode = argument
        self._append_message("system", f"Privacy mode set to {argument}.")

    def _goal_command(self, argument: str) -> None:
        runner = GoalRunner(self.runtime)
        if argument == "status":
            state = runner.status()
            self._append_message("system", "No goal recorded in this session." if state is None else str(state))
            return
        if argument == "clear":
            runner.clear()
            self._append_message("system", "Goal state cleared.")
            return
        if argument == "resume":
            self._start_worker("/goal resume", runner.resume)
            return
        objective, separator, verify = argument.partition(" --verify ")
        if not objective:
            self._append_message("error", "Usage: /goal <objective> [--verify <command>]")
            return
        self._start_worker(
            f"/goal {objective}",
            lambda: runner.run(objective, verify_command=verify.strip() if separator else None),
            user_prompt=f"/goal {objective}",
        )

    def _start_worker(
        self,
        label: str,
        work: Callable[[], str | dict[str, Any]],
        *,
        user_prompt: str | None = None,
    ) -> None:
        with self._lock:
            if self._busy:
                self._notice = "A turn is already running."
                self._application.invalidate()
                return
            self._busy = True
            self._partial = ""
            self._status = label
            self._notice = ""
            if user_prompt is not None:
                self._messages.append(("user", user_prompt))
        self._application.invalidate()

        def worker() -> None:
            try:
                result = work()
                if self.runtime.last_session_id:
                    self.runtime.session_id = self.runtime.last_session_id
                if isinstance(result, dict):
                    answer = str(result.get("summary", result))
                else:
                    answer = str(result or "")
                with self._lock:
                    streamed = bool(self._partial)
                    self._partial = ""
                    if answer:
                        self._messages.append(("assistant", answer))
                    elif streamed:
                        self._messages.append(("assistant", "[No final text returned.]"))
            except (OSError, ValueError, RuntimeError) as exc:
                with self._lock:
                    self._partial = ""
                    self._messages.append(("error", f"{type(exc).__name__}: {exc}"))
            finally:
                with self._lock:
                    self._busy = False
                    self._status = "Ready"
                self._application.invalidate()

        threading.Thread(target=worker, name="nextorca-tui-turn", daemon=True).start()

    def run(self) -> None:
        try:
            self._application.run()
        finally:
            # If the UI exits unexpectedly, any wait in the approval broker fails closed.
            self.approval.close()


def run_tui(
    runtime: AgentRuntime,
    approval: TerminalApprovalPolicy,
    *,
    input: Any | None = None,
    output: Any | None = None,
) -> None:
    """Run NextOrca in the full-screen terminal UI."""
    TerminalWorkspace(runtime, approval, input=input, output=output).run()
