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
