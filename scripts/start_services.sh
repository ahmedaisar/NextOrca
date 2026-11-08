#!/usr/bin/env bash
# Start llama-server and proxy, exporting PIDs for caller to manage.
# Source this file: source scripts/start_services.sh
set -euo pipefail

PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_ROOT="${NEXTORCA_WORKSPACE_ROOT:-$PROJ_DIR}"
if [ ! -d "$WORKSPACE_ROOT" ]; then
  echo "ERROR: NEXTORCA_WORKSPACE_ROOT is not an existing directory: $WORKSPACE_ROOT" >&2
  exit 1
fi
WORKSPACE_ROOT="$(cd "$WORKSPACE_ROOT" && pwd)"
export NEXTORCA_WORKSPACE_ROOT="$WORKSPACE_ROOT"

MODEL_PATH="$PROJ_DIR/models/LocoOperator-4B-GGUF/LocoOperator-4B.gguf"
if [ ! -f "$MODEL_PATH" ] && [ ! -L "$MODEL_PATH" ]; then
  echo "ERROR: Model not found at $MODEL_PATH"
  exit 1
fi

_loco_cleanup() {
  [ -n "${PROXY_PID:-}" ] && kill "$PROXY_PID" 2>/dev/null
  [ -n "${LLAMA_PID:-}" ] && kill "$LLAMA_PID" 2>/dev/null
  wait 2>/dev/null
}
trap _loco_cleanup EXIT

_loco_proxy_workspace() {
  local health_json reported_workspace
  health_json="$(curl -fsS --max-time 2 http://127.0.0.1:9091/health 2>/dev/null)" || return 1
  reported_workspace="$(printf '%s' "$health_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("workspace_root", ""))')" || return 2
  if [ "$reported_workspace" != "$NEXTORCA_WORKSPACE_ROOT" ]; then
    echo "ERROR: Proxy is serving workspace '$reported_workspace', but this task requires '$NEXTORCA_WORKSPACE_ROOT'." >&2
    echo "Stop the existing proxy and restart the analysis command." >&2
    return 2
  fi
  return 0
}

# Start llama-server if not already running.
if ! curl -fsS --max-time 2 http://127.0.0.1:8080/health >/dev/null 2>&1; then
  echo "Starting llama-server..."
  llama-server \
    --model "$MODEL_PATH" \
    --port 8080 --ctx-size 32768 -ngl 99 \
    > /dev/null 2>&1 &
  LLAMA_PID=$!
  llama_ready=0
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 http://127.0.0.1:8080/health >/dev/null 2>&1; then
      llama_ready=1
      break
    fi
    if ! kill -0 "$LLAMA_PID" 2>/dev/null; then
      echo "ERROR: llama-server failed to start" >&2
      exit 1
    fi
    sleep 1
  done
  if [ "$llama_ready" -ne 1 ]; then
    echo "ERROR: llama-server did not become ready within 30 seconds." >&2
    exit 1
  fi
else
  echo "llama-server already running on :8080"
fi

# Reuse only a proxy whose configured workspace matches this task.
if curl -fsS --max-time 2 http://127.0.0.1:9091/health >/dev/null 2>&1; then
  _loco_proxy_workspace
  echo "Proxy already running for workspace $NEXTORCA_WORKSPACE_ROOT"
else
  echo "Starting proxy for workspace $NEXTORCA_WORKSPACE_ROOT..."
  cd "$PROJ_DIR"
  uv run python scripts/proxy.py > /dev/null 2>&1 &
  PROXY_PID=$!
  proxy_ready=0
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 http://127.0.0.1:9091/health >/dev/null 2>&1; then
      _loco_proxy_workspace
      proxy_ready=1
      break
    fi
    if ! kill -0 "$PROXY_PID" 2>/dev/null; then
      echo "ERROR: proxy failed to start" >&2
      exit 1
    fi
    sleep 1
  done
  if [ "$proxy_ready" -ne 1 ]; then
    echo "ERROR: proxy did not become ready within 30 seconds." >&2
    exit 1
  fi
fi
