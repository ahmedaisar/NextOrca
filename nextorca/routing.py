from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from nextorca.provider import (
    ChatProvider,
    ProviderError,
    ProviderUnavailableError,
)
from nextorca.types import AssistantTurn

RouteMode = Literal["auto", "local", "cloud"]
PrivacyMode = Literal["balanced", "local-only"]

LOCAL_TASKS = frozenset({"explore", "explain"})


@dataclass(frozen=True)
class RouteDecision:
    task: str
    provider: str
    model: str
    reason: str
    fallback_from: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_task(messages: list[dict[str, Any]]) -> str:
    """Classify the most recent user request into a small, explainable task taxonomy."""
    user_text = ""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            user_text = content.lower()
        elif isinstance(content, list):
            user_text = " ".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ).lower()
        if user_text:
            break

    if any(term in user_text for term in ("pytest", "unit test", "test suite", "run tests", "failing test")):
        return "test"
    if any(term in user_text for term in ("debug", "bug", "traceback", "exception", "broken", "fix ")):
        return "debug"
    if user_text.lstrip().startswith(("where is ", "where are ")):
        return "explain"
    if any(term in user_text for term in ("implement", "refactor", "modify", "change ", "update ", "add ", "write ")):
        return "edit"
    if any(term in user_text for term in ("security", "audit", "review", "vulnerability", "code review")):
        return "review"
    if any(term in user_text for term in ("system design", "architecture design", "trade-off", "tradeoff", "design a", "plan the")):
        return "plan"
    if any(term in user_text for term in ("explain", "describe", "how does", "how do", "where is", "what does")):
        return "explain"
    return "explore"


RouteHandler = Callable[[RouteDecision], None]


class HybridRouter:
    """Task-aware provider router with explicit decisions and guarded local fallback.

    In auto mode, repository exploration and code explanation are routed locally.
    Editing, debugging, testing, review and planning use the cloud provider.
    A temporary local-provider outage may escalate to cloud. Cloud failures are not
    silently downgraded to a weaker local model.
    """

    def __init__(
        self,
        *,
        local_provider: ChatProvider | None,
        local_model: str | None,
        cloud_provider: ChatProvider | None,
        cloud_model: str | None,
        route_mode: RouteMode = "auto",
        privacy_mode: PrivacyMode = "balanced",
        on_route: RouteHandler | None = None,
    ) -> None:
        if route_mode not in {"auto", "local", "cloud"}:
            raise ValueError("route_mode must be auto, local or cloud.")
        if privacy_mode not in {"balanced", "local-only"}:
            raise ValueError("privacy_mode must be balanced or local-only.")
        if privacy_mode == "local-only" and route_mode == "cloud":
            raise ValueError("cloud routing is incompatible with local-only privacy mode.")
        if local_provider is not None and not local_model:
            raise ValueError("local_model is required when a local provider is configured.")
        if cloud_provider is not None and not cloud_model:
            raise ValueError("cloud_model is required when a cloud provider is configured.")
        if route_mode == "local" and local_provider is None:
            raise ValueError("Local routing requested, but no local provider is configured.")
        if route_mode == "cloud" and cloud_provider is None:
            raise ValueError("Cloud routing requested, but no cloud provider is configured.")
        if privacy_mode == "local-only" and local_provider is None:
            raise ValueError("Local-only privacy mode requires a local provider.")

        self.local_provider = local_provider
        self.local_model = local_model
        self.cloud_provider = cloud_provider
        self.cloud_model = cloud_model
        self.route_mode = route_mode
        self.privacy_mode = privacy_mode
        self.on_route = on_route
        self.last_decision: RouteDecision | None = None

    def _emit(self, decision: RouteDecision) -> None:
        self.last_decision = decision
        if self.on_route is not None:
            self.on_route(decision)

    def _select(self, messages: list[dict[str, Any]]) -> tuple[ChatProvider, RouteDecision]:
        task = classify_task(messages)
        if self.route_mode == "local" or self.privacy_mode == "local-only":
            if self.local_provider is None or self.local_model is None:
                raise ProviderError("No local provider is configured.")
            reason = (
                "manual local override"
                if self.route_mode == "local"
                else "local-only privacy policy"
            )
            decision = RouteDecision(task, "local", self.local_model, reason)
            return self.local_provider, decision

        if self.route_mode == "cloud":
            if self.cloud_provider is None or self.cloud_model is None:
                raise ProviderError("No cloud provider is configured.")
            decision = RouteDecision(task, "cloud", self.cloud_model, "manual cloud override")
            return self.cloud_provider, decision

        if task in LOCAL_TASKS and self.local_provider is not None and self.local_model is not None:
            return self.local_provider, RouteDecision(
                task,
                "local",
                self.local_model,
                "read-oriented task is suitable for local code intelligence",
            )
        if self.cloud_provider is not None and self.cloud_model is not None:
            reason = (
                "task requires stronger coding/reasoning capability"
                if task not in LOCAL_TASKS
                else "local provider unavailable; using cloud provider"
            )
            return self.cloud_provider, RouteDecision(task, "cloud", self.cloud_model, reason)
        raise ProviderError(
            f"Task class '{task}' requires a cloud provider in auto routing mode."
        )

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        provider, decision = self._select(messages)
        self._emit(decision)
        try:
            return provider.complete(
                model=decision.model,
                messages=messages,
                tools=tools,
            )
        except ProviderUnavailableError:
            if (
                decision.provider != "local"
                or self.route_mode != "auto"
                or self.privacy_mode == "local-only"
                or self.cloud_provider is None
                or self.cloud_model is None
            ):
                raise
            fallback = RouteDecision(
                task=decision.task,
                provider="cloud",
                model=self.cloud_model,
                reason="local provider unavailable; escalating to cloud",
                fallback_from="local",
            )
            self._emit(fallback)
            return self.cloud_provider.complete(
                model=fallback.model,
                messages=messages,
                tools=tools,
            )
