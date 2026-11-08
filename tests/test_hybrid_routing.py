from __future__ import annotations

import pytest

from nextorca.provider import ProviderError, ProviderUnavailableError
from nextorca.routing import HybridRouter, classify_task
from nextorca.types import AssistantTurn


class StubProvider:
    def __init__(self, name: str, result=None, error: Exception | None = None) -> None:
        self.name = name
        self.result = result or AssistantTurn(content=name)
        self.error = error
        self.calls = []

    def complete(self, *, model, messages, tools):
        self.calls.append({"model": model, "messages": messages, "tools": tools})
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Show me the repository layout", "explore"),
        ("Explain how the config loader works", "explain"),
        ("Implement a cache invalidation feature", "edit"),
        ("Fix the failing parser bug", "debug"),
        ("Review the code for security issues", "review"),
        ("Plan the architecture for multi-agent execution", "plan"),
        ("Run the pytest suite", "test"),
    ],
)
def test_task_classifier(prompt, expected):
    assert classify_task([{"role": "user", "content": prompt}]) == expected


def test_auto_mode_routes_exploration_to_local():
    local = StubProvider("local answer")
    cloud = StubProvider("cloud answer")
    decisions = []
    router = HybridRouter(
        local_provider=local,
        local_model="small-code-model",
        cloud_provider=cloud,
        cloud_model="strong-code-model",
        on_route=decisions.append,
    )

    result = router.complete(
        model="ignored",
        messages=[{"role": "user", "content": "Map the project structure"}],
        tools=[],
    )

    assert result.content == "local answer"
    assert len(local.calls) == 1
    assert cloud.calls == []
    assert decisions[0].provider == "local"
    assert decisions[0].reason


def test_auto_mode_routes_editing_to_cloud():
    local = StubProvider("local answer")
    cloud = StubProvider("cloud answer")
    decisions = []
    router = HybridRouter(
        local_provider=local,
        local_model="small-code-model",
        cloud_provider=cloud,
        cloud_model="strong-code-model",
        on_route=decisions.append,
    )

    result = router.complete(
        model="ignored",
        messages=[{"role": "user", "content": "Refactor the authentication flow"}],
        tools=[],
    )

    assert result.content == "cloud answer"
    assert local.calls == []
    assert cloud.calls[0]["model"] == "strong-code-model"
    assert decisions[0].provider == "cloud"


def test_auto_mode_escalates_local_availability_failure_to_cloud():
    local = StubProvider("local", error=ProviderUnavailableError("connection timeout"))
    cloud = StubProvider("cloud answer")
    decisions = []
    router = HybridRouter(
        local_provider=local,
        local_model="small",
        cloud_provider=cloud,
        cloud_model="large",
        on_route=decisions.append,
    )

    result = router.complete(
        model="ignored",
        messages=[{"role": "user", "content": "Find where the retry policy is defined"}],
        tools=[],
    )

    assert result.content == "cloud answer"
    assert len(local.calls) == 1
    assert len(cloud.calls) == 1
    assert decisions[-1].provider == "cloud"
    assert decisions[-1].fallback_from == "local"


def test_manual_local_override_does_not_fallback():
    local = StubProvider("local", error=ProviderUnavailableError("offline"))
    cloud = StubProvider("cloud")
    router = HybridRouter(
        local_provider=local,
        local_model="small",
        cloud_provider=cloud,
        cloud_model="large",
        route_mode="local",
    )

    with pytest.raises(ProviderUnavailableError):
        router.complete(
            model="ignored",
            messages=[{"role": "user", "content": "Explain the package structure"}],
            tools=[],
        )
    assert cloud.calls == []


def test_local_only_privacy_never_calls_cloud_or_falls_back():
    local = StubProvider("local", error=ProviderUnavailableError("offline"))
    cloud = StubProvider("cloud")
    router = HybridRouter(
        local_provider=local,
        local_model="small",
        cloud_provider=cloud,
        cloud_model="large",
        privacy_mode="local-only",
    )

    with pytest.raises(ProviderUnavailableError):
        router.complete(
            model="ignored",
            messages=[{"role": "user", "content": "Explain the package structure"}],
            tools=[],
        )
    assert cloud.calls == []


def test_auto_complex_task_requires_cloud_provider():
    local = StubProvider("local")
    router = HybridRouter(
        local_provider=local,
        local_model="small",
        cloud_provider=None,
        cloud_model=None,
    )
    with pytest.raises(ProviderError, match="requires a cloud provider"):
        router.complete(
            model="ignored",
            messages=[{"role": "user", "content": "Implement a new provider adapter"}],
            tools=[],
        )
    assert local.calls == []


def test_forced_cloud_mode_uses_cloud_provider():
    local = StubProvider("local")
    cloud = StubProvider("cloud")
    router = HybridRouter(
        local_provider=local,
        local_model="small",
        cloud_provider=cloud,
        cloud_model="large",
        route_mode="cloud",
    )
    result = router.complete(
        model="ignored",
        messages=[{"role": "user", "content": "Find the README"}],
        tools=[],
    )
    assert result.content == "cloud"
    assert local.calls == []


def test_local_only_privacy_rejects_forced_cloud_route():
    with pytest.raises(ValueError, match="incompatible"):
        HybridRouter(
            local_provider=StubProvider("local"),
            local_model="small",
            cloud_provider=StubProvider("cloud"),
            cloud_model="large",
            route_mode="cloud",
            privacy_mode="local-only",
        )
