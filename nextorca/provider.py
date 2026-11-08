from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

from nextorca.types import AssistantTurn, ProviderStreamChunk


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


class StreamingChatProvider(Protocol):
    """Optional streaming extension to the normalized provider contract."""

    def stream_complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[ProviderStreamChunk]:
        """Yield text deltas followed by one completed assistant turn."""
