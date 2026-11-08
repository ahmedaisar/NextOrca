import importlib.util
import json
import os
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_claude_settings.py"
SPEC = importlib.util.spec_from_file_location("generate_claude_settings", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_settings_never_persist_cloud_api_key(tmp_path):
    secret = "sk-or-v1-test-secret-that-must-not-be-written"
    path = MODULE.generate_settings(tmp_path, {"OPENROUTER_API_KEY": secret})
    settings_text = path.read_text(encoding="utf-8")
    settings = json.loads(settings_text)
    token_file = tmp_path / ".claude" / "proxy-token"

    assert secret not in settings_text
    assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == token_file.read_text().strip()
    assert settings["permissions"]["defaultMode"] == "plan"
    assert token_file.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o600


def test_settings_reuse_local_proxy_token(tmp_path):
    token_file = tmp_path / ".claude" / "proxy-token"
    token_file.parent.mkdir()
    token_file.write_text("x" * 64, encoding="utf-8")
    path = MODULE.generate_settings(tmp_path, {"OPENROUTER_API_KEY": "real-key"})
    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == "x" * 64


def test_missing_cloud_key_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        MODULE.generate_settings(tmp_path, {})


def test_placeholder_cloud_key_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        MODULE.generate_settings(
            tmp_path, {"OPENROUTER_API_KEY": MODULE.PLACEHOLDER_API_KEY}
        )


def test_token_symlink_is_rejected(tmp_path):
    target = tmp_path / "token-target"
    target.write_text("x" * 64, encoding="utf-8")
    token_file = tmp_path / ".claude" / "proxy-token"
    token_file.parent.mkdir()
    token_file.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        MODULE.generate_settings(tmp_path, {"OPENROUTER_API_KEY": "real-key"})
