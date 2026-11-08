from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from nextorca.openai_compatible import OpenAICompatibleProvider
from nextorca.runtime import AgentConfig, AgentRuntime
from nextorca.workspace import Workspace, build_workspace_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nextorca",
        description="Experimental local-first, read-only coding-agent runtime.",
    )
    parser.add_argument("prompt", help="Task or question for the coding agent.")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Repository workspace (default: current directory).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NEXTORCA_BASE_URL", "http://127.0.0.1:8080/v1"),
        help="OpenAI-compatible API base URL.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("NEXTORCA_MODEL", "local-model"),
        help="Model identifier served by the configured provider.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("NEXTORCA_API_KEY"),
        help="Provider API key (prefer NEXTORCA_API_KEY environment variable).",
    )
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--verbose", action="store_true", help="Print structured agent events to stderr.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        workspace = Workspace(args.workspace)
        provider = OpenAICompatibleProvider(args.base_url, api_key=args.api_key)
        runtime = AgentRuntime(
            provider=provider,
            model=args.model,
            tools=build_workspace_tools(workspace),
            config=AgentConfig(max_turns=args.max_turns),
            on_event=(
                lambda event: print(
                    json.dumps({"type": event.type, **event.data}),
                    file=sys.stderr,
                )
            )
            if args.verbose
            else None,
        )
        answer = runtime.run(args.prompt)
        print(answer)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"nextorca: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
