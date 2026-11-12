from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from nextorca import openai_compatible, provider, routing


ProviderFactory = Callable[..., provider.ChatProvider]
DEFAULT_PROVIDER_ADAPTER = "openai-compatible"


class ProviderRegistry:
    """Small registry of transport adapters that satisfy the provider.ChatProvider contract."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    @property
    def adapters(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))

    def register(
        self,
        name: str,
        factory: ProviderFactory,
        *,
        replace: bool = False,
    ) -> None:
        if not isinstance(name, str) or not name or name.strip() != name:
            raise ValueError("Provider adapter name must be a non-empty identifier.")
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Provider adapter names may contain only letters, digits, '-' and '_'.")
        if not callable(factory):
            raise TypeError("Provider adapter factory must be callable.")
        if name in self._factories and not replace:
            raise ValueError(f"Provider adapter '{name}' is already registered.")
        self._factories[name] = factory

    def create(
        self,
        name: str,
        *,
        base_url: str | None,
        api_key: str | None = None,
    ) -> provider.ChatProvider:
        factory = self._factories.get(name)
        if factory is None:
            available = ", ".join(self.adapters) or "(none)"
            raise provider.ProviderError(
                f"Unknown provider adapter '{name}'. Available adapters: {available}."
            )
        if not isinstance(base_url, str) or not base_url.strip():
            raise provider.ProviderError(f"Provider adapter '{name}' requires a base URL.")
        try:
            provider = factory(base_url=base_url, api_key=api_key)
        except (ValueError, TypeError) as exc:
            raise provider.ProviderError(
                f"Provider adapter '{name}' could not be configured: {type(exc).__name__}."
            ) from exc
        if not callable(getattr(provider, "complete", None)):
            raise provider.ProviderError(
                f"Provider adapter '{name}' did not create a provider.ChatProvider-compatible instance."
            )
        return provider


def create_default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        DEFAULT_PROVIDER_ADAPTER,
        lambda *, base_url, api_key=None: openai_compatible.OpenAICompatibleProvider(
            base_url,
            api_key=api_key,
        ),
    )
    return registry


@dataclass(frozen=True)
class ProviderEndpoint:
    adapter: str
    base_url: str | None
    model: str
    api_key: str | None = None


@dataclass(frozen=True)
class RuntimeProviderConfig:
    route_mode: str
    privacy_mode: str
    single: ProviderEndpoint
    local: ProviderEndpoint
    cloud: ProviderEndpoint


def build_runtime_provider(
    config: RuntimeProviderConfig,
    *,
    on_route: routing.RouteHandler | None = None,
    registry: ProviderRegistry | None = None,
) -> tuple[provider.ChatProvider, str]:
    """Construct the selected transport(s), then compose the existing router.

    The router receives only provider.ChatProvider instances. It has no dependency on
    provider-specific config or wire-protocol details.
    """
    active_registry = registry or create_default_provider_registry()
    if config.route_mode == "single":
        if config.privacy_mode == "local-only":
            raise ValueError(
                "local-only privacy mode requires --route-mode local or auto "
                "and a local model endpoint."
            )
        provider = active_registry.create(
            config.single.adapter,
            base_url=config.single.base_url,
            api_key=config.single.api_key,
        )
        return provider, config.single.model

    if config.route_mode not in {"auto", "local", "cloud"}:
        raise ValueError("route_mode must be single, auto, local or cloud.")
    if config.privacy_mode not in {"balanced", "local-only"}:
        raise ValueError("privacy_mode must be balanced or local-only.")

    local_provider = (
        active_registry.create(
            config.local.adapter,
            base_url=config.local.base_url,
            api_key=config.local.api_key,
        )
        if config.route_mode in {"auto", "local"}
        else None
    )
    cloud_provider = (
        active_registry.create(
            config.cloud.adapter,
            base_url=config.cloud.base_url,
            api_key=config.cloud.api_key,
        )
        if config.cloud.base_url and config.route_mode in {"auto", "cloud"}
        else None
    )
    router = routing.HybridRouter(
        local_provider=local_provider,
        local_model=config.local.model if local_provider is not None else None,
        cloud_provider=cloud_provider,
        cloud_model=config.cloud.model if cloud_provider is not None else None,
        route_mode=config.route_mode,  # type: ignore[arg-type]
        privacy_mode=config.privacy_mode,  # type: ignore[arg-type]
        on_route=on_route,
    )
    return router, "hybrid"
