#!/usr/bin/env bash
# Generate local Claude Code settings without persisting the upstream API key.
set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ_DIR"
uv run python scripts/generate_claude_settings.py
