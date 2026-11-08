from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from nextorca.openai_compatible import OpenAICompatibleProvider
from nextorca.permissions import InteractiveApprovalPolicy
from nextorca.runtime import AgentConfig, AgentRuntime, ReadOnlyPermissionPolicy
from nextorca.session_store import SQLiteSessionStore
from nextorca.workspace import Workspace, build_workspace_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nextorca",
        description="Local-first coding agent. Read-only by default; file edits require --allow-edits.",
    )
    parser.add_argument("prompt", nargs="?", help="Task or question for the coding agent.")
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
    parser.add_argument(
        "--session-db",
        type=Path,
        default=Path(
            os.environ.get(
                "NEXTORCA_SESSION_DB",
                str(Path.home() / ".nextorca" / "sessions.sqlite3"),
            )
        ),
        help="SQLite session database path.",
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("NEXTORCA_SESSION_ID"),
        help="Resume an existing session ID.",
    )
    parser.add_argument(
        "--allow-edits",
        action="store_true",
        help="Expose Write/Edit tools. Each file mutation requires interactive diff approval.",
    )
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument(
        "--undo-checkpoint",
        metavar="CHECKPOINT_ID",
        help="Undo a prior approved file change if the file has not changed since.",
    )
    operations.add_argument(
        "--list-checkpoints",
        action="store_true",
        help="List checkpoints for this workspace without contacting a model provider.",
    )
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print structured agent events to stderr.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        workspace = Workspace(args.workspace)
        session_store = SQLiteSessionStore(args.session_db)

        if args.undo_checkpoint:
            print(workspace.undo_checkpoint(args.undo_checkpoint, session_store))
            return 0
        if args.list_checkpoints:
            print(json.dumps(workspace.list_checkpoints(session_store), indent=2))
            return 0
        if not args.prompt:
            parser.error("provide a prompt, --undo-checkpoint, or --list-checkpoints")

        provider = OpenAICompatibleProvider(args.base_url, api_key=args.api_key)
        edits_enabled = bool(args.allow_edits)
        tools = build_workspace_tools(
            workspace,
            include_mutations=edits_enabled,
            checkpoint_store=session_store if edits_enabled else None,
        )
        policy = (
            InteractiveApprovalPolicy()
            if edits_enabled
            else ReadOnlyPermissionPolicy()
        )
        system_prompt = (
            "You are NextOrca, a careful coding assistant. Use the workspace tools to solve "
            "the user's task. Write and Edit operations are available, but every mutation "
            "requires the user to review and approve a diff before it is applied. Never claim "
            "a change was made unless the tool confirms it. Shell execution is unavailable."
            if edits_enabled
            else AgentConfig().system_prompt
        )
        runtime = AgentRuntime(
            provider=provider,
            model=args.model,
            tools=tools,
            permission_policy=policy,
            config=AgentConfig(max_turns=args.max_turns, system_prompt=system_prompt),
            on_event=(
                lambda event: print(
                    json.dumps({"type": event.type, **event.data}),
                    file=sys.stderr,
                )
            )
            if args.verbose
            else None,
            session_store=session_store,
            workspace_root=workspace.root,
            session_id=args.session_id,
        )
        answer = runtime.run(args.prompt)
        if runtime.last_session_id:
            print(f"Session ID: {runtime.last_session_id}", file=sys.stderr)
        print(answer)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"nextorca: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
