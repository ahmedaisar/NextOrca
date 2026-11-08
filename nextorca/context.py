from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any


class ContextLimitError(ValueError):
    """Required conversation context cannot fit the configured character budget."""


@dataclass(frozen=True)
class ContextReport:
    original_chars: int
    final_chars: int
    pruned_messages: int


class ContextBudget:
    """Deterministically prune old tool output while preserving user/system messages."""

    _TOOL_MARKER = "[Earlier tool output omitted to fit the model context budget.]"
    _ASSISTANT_MARKER = "[Earlier assistant text omitted to fit the model context budget.]"

    def __init__(
        self,
        *,
        max_chars: int = 80_000,
        preserve_recent_messages: int = 8,
    ) -> None:
        if max_chars < 1_024:
            raise ValueError("max_chars must be at least 1024.")
        if preserve_recent_messages < 1:
            raise ValueError("preserve_recent_messages must be at least 1.")
        self.max_chars = max_chars
        self.preserve_recent_messages = preserve_recent_messages

    @staticmethod
    def _size(messages: list[dict[str, Any]]) -> int:
        return len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))

    def fit(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], ContextReport]:
        result = copy.deepcopy(messages)
        original_size = self._size(result)
        if original_size <= self.max_chars:
            return result, ContextReport(original_size, original_size, 0)

        preserve_from = max(0, len(result) - self.preserve_recent_messages)
        pruned = 0

        # Older tool output is the least costly context to retrieve again.
        for index, message in enumerate(result):
            if index >= preserve_from or message.get("role") != "tool":
                continue
            content = message.get("content")
            if isinstance(content, str) and len(content) > len(self._TOOL_MARKER):
                message["content"] = self._TOOL_MARKER
                pruned += 1
                if self._size(result) <= self.max_chars:
                    break

        # If older tool output was insufficient, elide old assistant prose but retain
        # tool-call metadata so the remaining conversation stays structurally valid.
        if self._size(result) > self.max_chars:
            for index, message in enumerate(result):
                if index >= preserve_from or message.get("role") != "assistant":
                    continue
                content = message.get("content")
                if isinstance(content, str) and len(content) > len(self._ASSISTANT_MARKER):
                    message["content"] = self._ASSISTANT_MARKER
                    pruned += 1
                    if self._size(result) <= self.max_chars:
                        break

        final_size = self._size(result)
        if final_size > self.max_chars:
            raise ContextLimitError(
                "Required system/user context exceeds the configured context budget. "
                "Reduce the prompt or increase NEXTORCA_MAX_CONTEXT_CHARS."
            )
        return result, ContextReport(original_size, final_size, pruned)
