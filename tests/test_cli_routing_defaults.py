from __future__ import annotations

from nextorca.cli import build_parser


def test_parser_defaults_to_hybrid_when_local_and_cloud_endpoints_are_configured(monkeypatch):
    monkeypatch.delenv("NEXTORCA_ROUTE_MODE", raising=False)
    monkeypatch.setenv("NEXTORCA_LOCAL_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("NEXTORCA_CLOUD_BASE_URL", "https://openrouter.ai/api/v1")

    args = build_parser().parse_args([])

    assert args.route_mode == "auto"


def test_explicit_route_mode_environment_override_wins(monkeypatch):
    monkeypatch.setenv("NEXTORCA_ROUTE_MODE", "local")
    monkeypatch.setenv("NEXTORCA_LOCAL_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("NEXTORCA_CLOUD_BASE_URL", "https://openrouter.ai/api/v1")

    args = build_parser().parse_args([])

    assert args.route_mode == "local"


def test_parser_defaults_to_auto_ui_and_respects_environment_override(monkeypatch):
    monkeypatch.delenv("NEXTORCA_UI", raising=False)
    assert build_parser().parse_args([]).ui == "auto"

    monkeypatch.setenv("NEXTORCA_UI", "repl")
    assert build_parser().parse_args([]).ui == "repl"


def test_parser_accepts_explicit_ui_selection():
    assert build_parser().parse_args(["--ui", "tui"]).ui == "tui"
    assert build_parser().parse_args(["--ui", "repl"]).ui == "repl"


def test_provider_adapter_cli_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("NEXTORCA_PROVIDER_ADAPTER", raising=False)
    monkeypatch.delenv("NEXTORCA_LOCAL_PROVIDER_ADAPTER", raising=False)
    monkeypatch.delenv("NEXTORCA_CLOUD_PROVIDER_ADAPTER", raising=False)
    args = build_parser().parse_args([])

    assert args.provider_adapter == "openai-compatible"
    assert args.local_provider_adapter == "openai-compatible"
    assert args.cloud_provider_adapter == "openai-compatible"

    monkeypatch.setenv("NEXTORCA_PROVIDER_ADAPTER", "custom-single")
    monkeypatch.setenv("NEXTORCA_LOCAL_PROVIDER_ADAPTER", "custom-local")
    monkeypatch.setenv("NEXTORCA_CLOUD_PROVIDER_ADAPTER", "custom-cloud")
    args = build_parser().parse_args([])

    assert args.provider_adapter == "custom-single"
    assert args.local_provider_adapter == "custom-local"
    assert args.cloud_provider_adapter == "custom-cloud"


def test_provider_adapter_cli_flags_override_environment(monkeypatch):
    monkeypatch.setenv("NEXTORCA_PROVIDER_ADAPTER", "env-provider")
    monkeypatch.setenv("NEXTORCA_LOCAL_PROVIDER_ADAPTER", "env-local")
    monkeypatch.setenv("NEXTORCA_CLOUD_PROVIDER_ADAPTER", "env-cloud")

    args = build_parser().parse_args([
        "--provider-adapter", "cli-provider",
        "--local-provider-adapter", "cli-local",
        "--cloud-provider-adapter", "cli-cloud",
    ])

    assert args.provider_adapter == "cli-provider"
    assert args.local_provider_adapter == "cli-local"
    assert args.cloud_provider_adapter == "cli-cloud"
