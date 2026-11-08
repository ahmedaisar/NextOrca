from __future__ import annotations

import re
import subprocess
from typing import Any

from nextorca.runtime import AgentConfig, AgentRuntime, ReadOnlyPermissionPolicy
from nextorca.tool_registry import ToolSpec
from nextorca.workspace import Workspace, build_workspace_tools

MAX_GOAL_ITERATIONS = 5
MAX_VERIFY_TIMEOUT = 300
APPROVAL_VERDICT = re.compile(r"(?m)^VERDICT:\s*APPROVE\s*$")
REVISE_VERDICT = re.compile(r"(?m)^VERDICT:\s*REVISE\s*$")

REVIEWER_PROMPT = (
    "You are an independent reviewer. Inspect the current workspace and git diff using read-only "
    "tools. Evaluate whether the objective is satisfied and whether the reported verification is "
    "credible. Do not modify files or run shell commands. End with exactly one line: "
    "VERDICT: APPROVE or VERDICT: REVISE. Approve only when no important issue remains."
)


def _goal_done_tool(on_done) -> ToolSpec:
    return ToolSpec(
        name="GoalDone",
        description="Signal that the current /goal objective is complete and ready for independent review.",
        parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        handler=lambda _args: on_done(),
        read_only=True,
    )


def _git_diff_tool(workspace: Workspace) -> ToolSpec:
    def inspect(_arguments: dict[str, Any]) -> str:
        outputs = []
        for label, command in (
            ("Git status", ["git", "status", "--short"]),
            ("Unstaged diff", ["git", "diff", "--no-ext-diff", "--unified=3"]),
            ("Staged diff", ["git", "diff", "--cached", "--no-ext-diff", "--unified=3"]),
        ):
            try:
                result = subprocess.run(
                    command, cwd=workspace.root, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=10, check=False,
                )
                outputs.append(f"{label}:\n{result.stdout or result.stderr or '(empty)'}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                outputs.append(f"{label}: unavailable ({type(exc).__name__})")
        text = "\n\n".join(outputs)
        return text[:24_000] + ("\n[git review output truncated]" if len(text) > 24_000 else "")

    return ToolSpec(
        name="GitDiff",
        description="Inspect git status and staged/unstaged diffs. Read-only.",
        parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        handler=inspect,
        read_only=True,
    )


class GoalRunner:
    """Persistent goal loop with explicit verification and a fresh read-only reviewer."""

    def __init__(self, runtime: AgentRuntime, *, max_iterations: int = MAX_GOAL_ITERATIONS) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1.")
        self.runtime = runtime
        self.max_iterations = max_iterations

    def _session_id(self) -> str | None:
        return self.runtime.session_id or self.runtime.last_session_id

    def _save(self, state: dict[str, Any]) -> None:
        session_id = self._session_id()
        if session_id and self.runtime.session_store is not None:
            self.runtime.session_store.append_event(session_id, "goal_state", state)

    def status(self) -> dict[str, Any] | None:
        session_id = self._session_id()
        store = self.runtime.session_store
        if not session_id or store is None:
            return None
        states = [
            event for event in store.load_events(session_id)
            if event.get("type") == "goal_state"
        ]
        return states[-1] if states else None

    def clear(self) -> None:
        state = self.status()
        if state is not None:
            self._save({**state, "status": "cleared", "feedback": ""})

    def resume(self) -> str:
        state = self.status()
        if state is None or state.get("status") not in {"active", "paused"}:
            return "There is no active or paused goal in this session."
        return self.run(
            state["objective"],
            verify_command=state.get("verify_command"),
            initial_feedback=state.get("feedback", ""),
            start_iteration=int(state.get("iteration", 0)),
        )

    def _verify(self, command: str | None) -> tuple[bool, str]:
        if not command:
            return True, "No verification command configured."
        try:
            spec = self.runtime.tools.get("Shell")
            arguments = {"command": command, "timeout_seconds": MAX_VERIFY_TIMEOUT}
            prepared = self.runtime.tools.prepare(spec, arguments)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            return False, f"Could not prepare verification: {type(exc).__name__}: {exc}"
        if prepared is None:
            return False, "Verification command has no reviewable preview."
        try:
            approved = self.runtime.permission_policy.authorize(
                spec, arguments, preview=prepared.preview
            )
        except (EOFError, KeyboardInterrupt):
            approved = False
        if not approved:
            return False, "Verification command was not approved."
        try:
            output = self.runtime.tools.execute_prepared(prepared)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            return False, f"Verification failed: {type(exc).__name__}: {exc}"
        return output.startswith("Exit code: 0"), output

    def _review(
        self, objective: str, worker_answer: str, verify_command: str | None,
        verify_ok: bool, verify_output: str,
    ) -> tuple[bool, str]:
        if not self.runtime.workspace_root:
            return False, "Independent review requires a configured workspace."
        workspace = Workspace(self.runtime.workspace_root)
        tools = build_workspace_tools(workspace)
        tools.register(_git_diff_tool(workspace))
        reviewer = AgentRuntime(
            provider=self.runtime.provider,
            model=self.runtime.model,
            tools=tools,
            permission_policy=ReadOnlyPermissionPolicy(),
            config=AgentConfig(
                max_turns=8, max_tool_calls=24, system_prompt=REVIEWER_PROMPT
            ),
            session_store=self.runtime.session_store,
            workspace_root=self.runtime.workspace_root,
        )
        prompt = (
            f"Objective:\n{objective}\n\nWorker report:\n{worker_answer}\n\n"
            f"Verification command: {verify_command or '(not configured)'}\n"
            f"Verification passed: {verify_ok}\nVerification output:\n{verify_output}\n\n"
            "Inspect the current repository independently and provide your verdict."
        )
        try:
            answer = reviewer.run(prompt)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            return False, f"Reviewer failed: {type(exc).__name__}: {exc}"
        if REVISE_VERDICT.search(answer):
            return False, answer
        if APPROVAL_VERDICT.search(answer):
            return True, answer
        return False, f"Reviewer did not provide an explicit verdict: {answer}"

    def run(
        self, objective: str, *, verify_command: str | None = None,
        initial_feedback: str = "", start_iteration: int = 0,
    ) -> str:
        if not objective.strip():
            raise ValueError("Goal objective must not be empty.")
        if verify_command is not None and not verify_command.strip():
            verify_command = None
        if self.runtime.session_store is not None and self._session_id() is None:
            if self.runtime.workspace_root is None:
                raise ValueError("A workspace is required to persist a goal.")
            identifier = self.runtime.session_store.create_session(
                workspace=self.runtime.workspace_root, model=self.runtime.model
            )
            self.runtime.session_id = identifier
            self.runtime.last_session_id = identifier

        feedback = initial_feedback
        last_answer = ""
        total_iteration = start_iteration
        self._save({
            "objective": objective, "verify_command": verify_command,
            "iteration": start_iteration, "status": "active", "feedback": feedback,
        })
        for attempt in range(self.max_iterations):
            total_iteration = start_iteration + attempt + 1
            requested = False

            def mark_done() -> str:
                nonlocal requested
                requested = True
                return "Completion requested. Verification and an independent review will now run."

            self.runtime.tools.register(_goal_done_tool(mark_done))
            try:
                prompt = (
                    f"Work toward this goal until it is genuinely complete:\n{objective}\n\n"
                    "Use the available coding tools, make the necessary changes and run relevant checks. "
                    "Call GoalDone only when implementation is complete."
                )
                if feedback:
                    prompt += f"\n\nFeedback from the previous attempt:\n{feedback}"
                last_answer = self.runtime.run(prompt)
            finally:
                self.runtime.tools.unregister("GoalDone")

            if not requested:
                feedback = (
                    "You have not called GoalDone. Continue working; call it only after the "
                    "objective is complete and relevant checks have run."
                )
                self._save({
                    "objective": objective, "verify_command": verify_command,
                    "iteration": total_iteration, "status": "active", "feedback": feedback,
                })
                continue

            verify_ok, verify_output = self._verify(verify_command)
            review_ok, review_output = self._review(
                objective, last_answer, verify_command, verify_ok, verify_output
            )
            if verify_ok and review_ok:
                self._save({
                    "objective": objective, "verify_command": verify_command,
                    "iteration": total_iteration, "status": "completed", "feedback": "",
                    "verification": verify_output, "review": review_output,
                })
                return (
                    f"Goal completed and independently approved after {total_iteration} attempt(s).\n"
                    f"Verification: {verify_output}\n\nReviewer: {review_output}"
                )

            feedback = (
                f"Verification passed: {verify_ok}.\nVerification output:\n{verify_output}\n\n"
                f"Independent review passed: {review_ok}.\nReviewer feedback:\n{review_output}\n\n"
                "Address the issues, rerun checks, then call GoalDone again."
            )
            self._save({
                "objective": objective, "verify_command": verify_command,
                "iteration": total_iteration, "status": "active", "feedback": feedback,
                "verification": verify_output, "review": review_output,
            })

        self._save({
            "objective": objective, "verify_command": verify_command,
            "iteration": total_iteration, "status": "paused", "feedback": feedback,
        })
        return (
            f"Goal paused after {self.max_iterations} attempts. Use /goal resume to continue.\n"
            f"Last worker response: {last_answer}\n\nFeedback: {feedback}"
        )
