from __future__ import annotations

from nextorca.runtime import AgentRuntime
from nextorca.tool_registry import ToolRegistry
from nextorca.types import AssistantTurn, ProviderStreamChunk


class StreamingProvider:
    def complete(self, **_kwargs):
        raise AssertionError("streaming method should be used")

    def stream_complete(self, **_kwargs):
        yield ProviderStreamChunk(content_delta="Hello ")
        yield ProviderStreamChunk(final_turn=AssistantTurn(content="Hello world"))


def test_runtime_emits_stream_deltas_and_retains_final_turn():
    events = []
    runtime = AgentRuntime(
        provider=StreamingProvider(),
        model="mock",
        tools=ToolRegistry(),
        on_event=events.append,
    )

    answer = runtime.run("Say hello")

    assert answer == "Hello world"
    assert runtime.last_turn_streamed is True
    delta = next(event for event in events if event.type == "assistant_delta")
    assert delta.data["content"] == "Hello "
