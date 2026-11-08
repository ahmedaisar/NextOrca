from __future__ import annotations

from collections.abc import Callable
import sys
from typing import TextIO

from nextorca.tool_registry import ToolSpec


class InteractiveApprovalPolicy:
    """Allow reads automatically; require explicit interactive approval for mutations."""

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] = input,
        output: TextIO | None = None,
    ) -> None:
        self.input_fn = input_fn
        self.output = output or sys.stderr

    def authorize(
        self,
        tool: ToolSpec,
        arguments: dict,
        *,
        preview: str | None = None,
    ) -> bool:
        if tool.read_only:
            return True
        if not preview:
            print(
                f"Refusing {tool.name}: there is no reviewable diff.",
                file=self.output,
            )
            return False
        print(f"\nApproval required: {tool.name}", file=self.output)
        print(preview, file=self.output)
        try:
            answer = self.input_fn("Apply this change? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("Approval cancelled.", file=self.output)
            return False
        approved = answer in {"y", "yes"}
        if not approved:
            print("Change declined; workspace unchanged.", file=self.output)
        return approved
