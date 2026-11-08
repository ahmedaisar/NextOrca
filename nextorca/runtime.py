from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Protocol

from nextorca.provider import ChatProvider, ProviderError
from nextorca.tool_registry import (
    ToolExecutionError,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
)
from nextorca.types import AgentEvent, AssistantTurn, ToolCall


class AgentRuntimeError(RuntimeError):
    """The agent could not safely complete its turn budget."""


class PermissionPolicy(Protocol):
    def authorize(self, tool: ToolSpec, arguments: dict[str, Any]) -> bool:
        """Return True only when this invocation is permitted."""


class ReadOnlyPermissionPolicy:
    """Safe default policy: only explicitly read-only registered tools may run."""

    def authorize(self, tool: ToolSpec, arguments: dict[str, Any]) -> bool:
        return tool.read_only


@dataclass(frozen=True)
class AgentConfig:
    max_turns: int = 12
    max_tool_calls: int = 40
    max_tool_output_chars: int = 12_000
    system_prompt: str = (
        "You are NextOrca, a careful coding assistant. "
        "Use the available tools to inspect the current workspace. "
        "Do not claim to have run commands or changed files. "
        "The available tools are read-only."
    )

    def __post_init__(self) -> None:
        if self.max_turns < 1:
            raise ValueError("max_turns must be at least 1.")
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least 1.")
        if self.max_tool_output_chars < 256:
            raise ValueError("max_tool_output_chars must be at least 256.")


EventHandler = Callable[[AgentEvent], None]


class AgentRuntime:
    """Provider-independent model/tool loop with policy-checked tool execution."""

    def __init__(
        self,
        *,
        provider: ChatProvider,
        model: str,
        tools: ToolRegistry,
        permission_policy: PermissionPolicy | None = None,
        config: AgentConfig | None = None,
        on_event: EventHandler | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.tools = tools
        self.permission_policy = permission_policy or ReadOnlyPermissionPolicy()
        self.config = config or AgentConfig()
        self.on_event = on_event

    def _emit(self, event_type: str, **data: Any) -> None:
        if self.on_event is not None:
            self.on_event(AgentEvent(type=event_type, data=data))

    def _tool_result(self, call: ToolCall) -> str:
        try:
            spec = self.tools.get(call.name)
            if not self.permission_policy.authorize(spec, call.arguments):
                self._emit("tool_denied", tool=call.name)
                return f"Permission denied: tool '{call.name}' is not allowed by the active policy."
            result = self.tools.execute(call.name, call.arguments)
        except (ToolValidationError, ToolExecutionError) as exc:
            self._emit("tool_error", tool=call.name, error=type(exc).__name__)
            return f"Tool error: {exc}"

        if len(result) > self.config.max_tool_output_chars:
            result = result[: self.config.max_tool_output_chars] + "\n[tool output truncated]"
        self._emit("tool_completed", tool=call.name, output_chars=len(result))
        return result

    @staticmethod
    def _assistant_message(turn: AssistantTurn) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": turn.content or None}
        if turn.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in turn.tool_calls
            ]
        return message

    def run(self, prompt: str) -> str:
        if not prompt or not prompt.strip():
            raise ValueError("A non-empty prompt is required.")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": prompt},
        ]
        tool_calls_executed = 0
        schemas = self.tools.provider_tools()

        for turn_index in range(self.config.max_turns):
            self._emit("model_turn_started", turn=turn_index + 1)
            try:
                response = self.provider.complete(
                    model=self.model,
                    messages=messages,
                    tools=schemas,
                )
            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError("Model provider request failed.") from exc

            if not isinstance(response, AssistantTurn):
                raise AgentRuntimeError("Provider returned an invalid normalized response.")
            messages.append(self._assistant_message(response))
            self._emit(
                "model_turn_completed",
                turn=turn_index + 1,
                tool_calls=len(response.tool_calls),
            )

            if not response.tool_calls:
                return response.content.strip()

            for call in response.tool_calls:
                tool_calls_executed += 1
                if tool_calls_executed > self.config.max_tool_calls:
                    raise AgentRuntimeError("Maximum tool-call budget exceeded.")
                self._emit("tool_started", tool=call.name, call_id=call.id)
                result = self._tool_result(call)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": result,
                    }
                )

        raise AgentRuntimeError(
            f"Agent did not finish within {self.config.max_turns} model turns."
        )
