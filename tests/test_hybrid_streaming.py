from __future__ import annotations

import pytest

from nextorca.provider import ProviderUnavailableError
from nextorca.routing import HybridRouter
from nextorca.types import AssistantTurn, ProviderStreamChunk


class LocalUnavailable:
    def complete(self, **_kwargs):
        raise ProviderUnavailableError("local endpoint unavailable")

    def stream_complete(self, **_kwargs):
        raise ProviderUnavailableError("local endpoint unavailable")
        yield  # pragma: no cover


class LocalPartialThenUnavailable:
    def complete(self, **_kwargs):
        raise AssertionError("streaming should be used")

    def stream_complete(self, **_kwargs):
        yield ProviderStreamChunk(content_delta="partial local output")
        raise ProviderUnavailableError("local stream interrupted")


class CloudProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, **_kwargs):
        self.calls += 1
        return AssistantTurn(content="cloud answer")

    def stream_complete(self, **_kwargs):
        self.calls += 1
        yield ProviderStreamChunk(content_delta="cloud ")
        yield ProviderStreamChunk(final_turn=AssistantTurn(content="cloud answer"))


def _router(local, cloud, *, privacy_mode="balanced"):
    return HybridRouter(
        local_provider=local,
        local_model="local",
        cloud_provider=cloud,
        cloud_model="cloud",
        route_mode="auto",
        privacy_mode=privacy_mode,
    )


def test_streaming_router_falls_back_before_any_local_output():
    cloud = CloudProvider()
    router = _router(LocalUnavailable(), cloud)

    chunks = list(
        router.stream_complete(
            model="ignored",
            messages=[{"role": "user", "content": "Explain this module"}],
            tools=[],
        )
    )

    assert chunks[-1].final_turn.content == "cloud answer"
    assert cloud.calls == 1
    assert router.last_decision.provider == "cloud"
    assert router.last_decision.fallback_from == "local"


def test_streaming_router_never_switches_provider_after_partial_output():
    cloud = CloudProvider()
    router = _router(LocalPartialThenUnavailable(), cloud)

    with pytest.raises(ProviderUnavailableError):
        list(
            router.stream_complete(
                model="ignored",
                messages=[{"role": "user", "content": "Explain this module"}],
                tools=[],
            )
        )

    assert cloud.calls == 0


def test_local_only_streaming_never_falls_back_to_cloud():
    cloud = CloudProvider()
    router = _router(LocalUnavailable(), cloud, privacy_mode="local-only")

    with pytest.raises(ProviderUnavailableError):
        list(
            router.stream_complete(
                model="ignored",
                messages=[{"role": "user", "content": "Explain this module"}],
                tools=[],
            )
        )

    assert cloud.calls == 0
