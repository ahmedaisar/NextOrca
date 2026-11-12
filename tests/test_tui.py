from __future__ import annotations

import threading
import time
from typing import Any

from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from nextorca.runtime import AgentRuntime
from nextorca.tool_registry import ToolRegistry, ToolSpec
from nextorca.tui import TerminalApprovalPolicy, TerminalWorkspace
from nextorca.types import AgentEvent, AssistantTurn


class _Provider:
    def complete(self, **_kwargs: Any) -> AssistantTurn:
        return AssistantTurn(content="unused")


class _SmallTerminalOutput(DummyOutput):
    def get_size(self) -> Size:
        return Size(rows=9, columns=36)


def _runtime() -> AgentRuntime:
    return AgentRuntime(provider=_Provider(), model="mock", tools=ToolRegistry())


def _mutating_tool(*, read_only: bool = False) -> ToolSpec:
    return ToolSpec(
        name="Write",
        description="Write a file.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=lambda _args: "changed",
        read_only=read_only,
    )


def test_tui_approval_allows_read_only_tools_without_prompt():
    policy = TerminalApprovalPolicy(timeout_seconds=0.01)

    assert policy.authorize(_mutating_tool(read_only=True), {})


def test_tui_approval_denies_mutations_without_preview():
    policy = TerminalApprovalPolicy(timeout_seconds=0.01)

    assert not policy.authorize(_mutating_tool(), {}, preview=None)


def test_tui_approval_waits_for_an_explicit_decision():
    policy = TerminalApprovalPolicy(timeout_seconds=1)
    result: list[bool] = []
    thread = threading.Thread(
        target=lambda: result.append(
            policy.authorize(_mutating_tool(), {}, preview="Write file: README.md")
        )
    )
    thread.start()

    pending = None
    deadline = time.monotonic() + 0.5
    while pending is None and time.monotonic() < deadline:
        pending = policy.pending
        time.sleep(0.002)

    assert pending is not None
    assert pending.tool_name == "Write"
    assert "README.md" in pending.preview
    assert policy.resolve(True)
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert result == [True]
    assert policy.pending is None


def test_tui_approval_timeout_fails_closed():
    policy = TerminalApprovalPolicy(timeout_seconds=0.01)

    assert not policy.authorize(_mutating_tool(), {}, preview="review this")
    assert policy.pending is None


def test_tui_renders_streams_and_tool_lifecycle_events():
    runtime = _runtime()
    ui = TerminalWorkspace(runtime, TerminalApprovalPolicy())

    ui._handle_event(AgentEvent("assistant_delta", {"content": "partial response"}))
    ui._handle_event(AgentEvent("tool_started", {"tool": "Write"}))
    ui._handle_event(AgentEvent("tool_completed", {"tool": "Write", "output_chars": 12}))
    ui._handle_event(AgentEvent("tool_denied", {"tool": "Shell"}))
    ui._handle_event(AgentEvent("tool_error", {"tool": "Grep", "error": "ToolExecutionError"}))

    rendered = "".join(text for _style, text in ui._transcript_fragments())

    assert "partial response" in rendered
    assert "Started Write" in rendered
    assert "Completed Write" in rendered
    assert "Denied Shell" in rendered
    assert "Grep" in rendered


def test_tui_application_runs_full_screen_and_restores_after_quit_on_small_terminal():
    runtime = _runtime()
    approval = TerminalApprovalPolicy()

    with create_pipe_input() as terminal_input:
        terminal_input.send_text("\x11")
        ui = TerminalWorkspace(
            runtime,
            approval,
            input=terminal_input,
            output=_SmallTerminalOutput(),
        )
        assert ui.application.full_screen is True

        ui.run()

    assert not approval.is_pending()
