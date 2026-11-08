"""Generate local Claude Code settings without copying cloud credentials to disk."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from pathlib import Path
from collections.abc import Mapping

from dotenv import dotenv_values

PLACEHOLDER_API_KEY = "sk-or-v1-your-key-here"


def _atomic_private_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _load_cloud_key(project_root: Path, environ: Mapping[str, str]) -> str:
    env_file = project_root / ".env"
    values = dotenv_values(env_file) if env_file.exists() else {}
    key = environ.get("OPENROUTER_API_KEY") or values.get("OPENROUTER_API_KEY") or ""
    if not key or key == PLACEHOLDER_API_KEY:
        raise ValueError(
            "Set a valid OPENROUTER_API_KEY in .env or the process environment."
        )
    return str(key)


def _get_or_create_proxy_token(project_root: Path) -> str:
    token_path = project_root / ".claude" / "proxy-token"
    if token_path.is_symlink():
        raise ValueError("Refusing to use a symlink as the local proxy token file.")
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise ValueError("Existing local proxy token is invalid; remove it and rerun setup.")
        os.chmod(token_path, 0o600)
        return token

    token = secrets.token_urlsafe(48)
    _atomic_private_write(token_path, token + "\n")
    return token


def generate_settings(
    project_root: Path, environ: Mapping[str, str] | None = None
) -> Path:
    """Validate credentials, create a local-only proxy token, and write settings.

    The OpenRouter key is checked but is never serialized into the settings file.
    """
    project_root = Path(project_root).resolve()
    environment = os.environ if environ is None else environ
    _load_cloud_key(project_root, environment)
    proxy_token = _get_or_create_proxy_token(project_root)

    settings = {
        "env": {
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:9091",
            "ANTHROPIC_AUTH_TOKEN": proxy_token,
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "qwen/qwen3-coder-next",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-5-20251001",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "qwen/qwen3-coder-next",
        },
        "permissions": {"defaultMode": "plan"},
    }
    settings_path = project_root / ".claude" / "settings.local.json"
    _atomic_private_write(
        settings_path,
        json.dumps(settings, indent=2, sort_keys=True) + "\n",
    )
    return settings_path


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    destination = generate_settings(root)
    print(f"Generated private local settings at {destination}")
