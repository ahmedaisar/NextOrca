from __future__ import annotations

from typing import Any

import pytest

from nextorca.anthropic import AnthropicMessagesProvider
from nextorca.openai_compatible import OpenAICompatibleProvider
from nextorca.provider import ProviderError
from nextorca.provider_registry import (
    DEFAULT_PROVIDER_ADAPTER,
    ProviderEndpoint,
    ProviderRegistry,
    RuntimeProviderConfig,
    build_runtime_provider,
    create_default_provider_registry,
)
from nextorca.routing import HybridRouter
from nextorca.types import AssistantTurn


class _StubProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, model, messages, tools):
        self.calls.append({"model": model, "messages": messages, "tools": tools})
        return AssistantTurn(content=self.name)

    def stream_complete(self, **_kwargs):
        yield from ()


def _config(
    mode: str,
    *,
    privacy: str = "balanced",
    single_adapter: str = "fake",
    local_adapter: str = "fake",
    cloud_adapter: str = "fake",
    cloud_url: str | None = "https://cloud.example/v1",
) -> RuntimeProviderConfig:
    return RuntimeProviderConfig(
        route_mode=mode,
        privacy_mode=privacy,
        single=ProviderEndpoint(single_adapter, "https://single.example/v1", "single-model", "s-key"),
        local=ProviderEndpoint(local_adapter, "http://127.0.0.1:8080/v1", "local-model", "l-key"),
        cloud=ProviderEndpoint(cloud_adapter, cloud_url, "cloud-model", "c-key"),
    )


def _stub_registry() -> tuple[ProviderRegistry, list[dict[str, Any]]]:
    registry = ProviderRegistry()
    created: list[dict[str, Any]] = []

    def factory(*, base_url, api_key=None):
        created.append({"base_url": base_url, "api_key": api_key})
        return _StubProvider(base_url)

    registry.register("fake", factory)
    return registry, created


def test_default_registry_exposes_tested_adapters_and_keeps_openai_default():
    registry = create_default_provider_registry()

    assert registry.adapters == ("anthropic", DEFAULT_PROVIDER_ADAPTER)
    provider = registry.create(
        DEFAULT_PROVIDER_ADAPTER,
        base_url="https://api.example/v1",
        api_key="test-key",
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.endpoint == "https://api.example/v1/chat/completions"
    assert provider.api_key == "test-key"

    anthropic_provider = registry.create("anthropic", base_url=None, api_key="anthropic-key")
    assert isinstance(anthropic_provider, AnthropicMessagesProvider)
    assert anthropic_provider.endpoint == "https://api.anthropic.com/v1/messages"

    with pytest.raises(ProviderError, match="requires a base URL"):
        registry.create(DEFAULT_PROVIDER_ADAPTER, base_url=None)


def test_registry_rejects_duplicate_and_unknown_adapter_names():
    registry = ProviderRegistry()
    registry.register("fake", lambda **_kwargs: _StubProvider("fake"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register("fake", lambda **_kwargs: _StubProvider("other"))
    with pytest.raises(ProviderError, match="Unknown provider adapter"):
        registry.create("missing", base_url="https://api.example/v1")


def test_registry_rejects_invalid_names_and_non_provider_factories():
    registry = ProviderRegistry()
    with pytest.raises(ValueError, match="identifier"):
        registry.register("not a name", lambda **_kwargs: _StubProvider("fake"))
    registry.register("invalid", lambda **_kwargs: object())

    with pytest.raises(ProviderError, match="ChatProvider-compatible"):
        registry.create("invalid", base_url="https://api.example/v1")


def test_registry_requires_a_base_url_before_calling_adapter_factory():
    registry, created = _stub_registry()

    with pytest.raises(ProviderError, match="requires a base URL"):
        registry.create("fake", base_url=None)

    assert created == []


def test_build_single_provider_preserves_model_and_endpoint_configuration():
    registry, created = _stub_registry()

    provider, model = build_runtime_provider(_config("single"), registry=registry)

    assert isinstance(provider, _StubProvider)
    assert provider.name == "https://single.example/v1"
    assert model == "single-model"
    assert created == [{"base_url": "https://single.example/v1", "api_key": "s-key"}]


def test_build_single_provider_rejects_local_only_mode():
    registry, created = _stub_registry()

    with pytest.raises(ValueError, match="local-only privacy mode"):
        build_runtime_provider(_config("single", privacy="local-only"), registry=registry)

    assert created == []


def test_build_auto_router_preserves_local_and_cloud_selection():
    registry, created = _stub_registry()
    decisions = []
    provider, model = build_runtime_provider(
        _config("auto"),
        registry=registry,
        on_route=decisions.append,
    )

    assert isinstance(provider, HybridRouter)
    assert model == "hybrid"
    local = provider.local_provider
    cloud = provider.cloud_provider
    assert isinstance(local, _StubProvider)
    assert isinstance(cloud, _StubProvider)

    local_result = provider.complete(
        model=model,
        messages=[{"role": "user", "content": "Explain the package structure"}],
        tools=[],
    )
    cloud_result = provider.complete(
        model=model,
        messages=[{"role": "user", "content": "Implement a cache invalidation feature"}],
        tools=[],
    )

    assert local_result.content == "http://127.0.0.1:8080/v1"
    assert cloud_result.content == "https://cloud.example/v1"
    assert [item.provider for item in decisions] == ["local", "cloud"]
    assert created == [
        {"base_url": "http://127.0.0.1:8080/v1", "api_key": "l-key"},
        {"base_url": "https://cloud.example/v1", "api_key": "c-key"},
    ]


def test_build_local_only_router_never_constructs_cloud_adapter():
    registry, created = _stub_registry()
    provider, model = build_runtime_provider(
        _config("auto", privacy="local-only"),
        registry=registry,
    )

    assert isinstance(provider, HybridRouter)
    assert model == "hybrid"
    assert provider.privacy_mode == "local-only"
    assert provider.cloud_provider is None
    assert [item["base_url"] for item in created] == ["http://127.0.0.1:8080/v1"]


def test_build_manual_cloud_router_does_not_construct_local_adapter():
    registry, created = _stub_registry()
    provider, model = build_runtime_provider(_config("cloud"), registry=registry)

    assert isinstance(provider, HybridRouter)
    assert model == "hybrid"
    assert provider.local_provider is None
    assert isinstance(provider.cloud_provider, _StubProvider)
    assert [item["base_url"] for item in created] == ["https://cloud.example/v1"]


def test_build_hybrid_router_rejects_unknown_adapter_without_fallback():
    registry, _created = _stub_registry()

    with pytest.raises(ProviderError, match="Unknown provider adapter"):
        build_runtime_provider(_config("auto", local_adapter="missing"), registry=registry)


def test_build_cloud_route_is_rejected_in_local_only_mode_without_constructing_adapters():
    registry, created = _stub_registry()

    with pytest.raises(ValueError, match="incompatible"):
        build_runtime_provider(_config("cloud", privacy="local-only"), registry=registry)

    assert created == []


def test_native_provider_can_be_constructed_without_a_custom_base_url():
    registry = create_default_provider_registry()
    provider = registry.create("anthropic", base_url=None, api_key="test-key")

    assert isinstance(provider, AnthropicMessagesProvider)
    assert registry.requires_base_url("anthropic") is False
    assert registry.supports_local_only("anthropic") is False
    assert registry.supports_local_only(DEFAULT_PROVIDER_ADAPTER) is True


def test_local_route_does_not_validate_an_unselected_cloud_adapter():
    registry, created = _stub_registry()
    config = _config("local", cloud_adapter="not-installed", cloud_url=None)

    provider, model = build_runtime_provider(config, registry=registry)

    assert isinstance(provider, HybridRouter)
    assert model == "hybrid"
    assert provider.cloud_provider is None
    assert [item["base_url"] for item in created] == ["http://127.0.0.1:8080/v1"]


def test_local_route_rejects_anthropic_as_a_local_provider():
    config = _config("local", local_adapter="anthropic")

    with pytest.raises(ValueError, match="cannot be configured as a local provider"):
        build_runtime_provider(config)
