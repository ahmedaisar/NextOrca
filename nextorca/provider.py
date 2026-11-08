from __future__ import annotations

from typing import Any, Protocol

from nextorca.types import AssistantTurn


class ProviderError(RuntimeError):
    """A model provider returned an invalid request or response."""


class ProviderUnavailableError(ProviderError):
    """A provider is temporarily unavailable and another route may be attempted."""


class ChatProvider(Protocol):
    """Provider contract used by the agent loop."""

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        """Return a normalized assistant turn."""
