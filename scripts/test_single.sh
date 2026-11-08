#!/usr/bin/env bash
# Run one strictly read-only analysis. The shell saves the agent's stdout.
set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
"$PROJ_DIR/scripts/setup.sh"

PROJECT="${1:-tqdm}"
QUERY="${2:-How does tqdm detect if running in a Jupyter notebook?}"

if [[ ! "$PROJECT" =~ ^[A-Za-z0-9._-]+$ ]] || [[ "$PROJECT" == "." || "$PROJECT" == ".." ]]; then
  echo "ERROR: project must be a simple directory name." >&2
  exit 2
fi
REPO_DIR="$PROJ_DIR/data/repos/$PROJECT"
OUTPUT_DIR="$PROJ_DIR/data/outputs/$PROJECT"
OUTPUT_FILE="$OUTPUT_DIR/test.md"

if [ ! -d "$REPO_DIR" ]; then
  echo "ERROR: repository directory not found: $REPO_DIR" >&2
  exit 1
fi

export NEXTORCA_WORKSPACE_ROOT="$REPO_DIR"
source "$PROJ_DIR/scripts/start_services.sh"
mkdir -p "$OUTPUT_DIR"

echo "Project: $PROJECT"
echo "Query: $QUERY"
echo "Permission mode: plan (read-only)"
echo "---"

cd "$PROJ_DIR"
tmp_output="$(mktemp "$OUTPUT_DIR/.test.XXXXXX")"
trap 'rm -f "$tmp_output"' EXIT
prompt="Analyze the $PROJECT codebase at $REPO_DIR to answer: $QUERY. Return the complete answer as stdout. Do not modify files."

if printf '%s\n' "$prompt" | claude -p \
  --permission-mode plan \
  --model sonnet \
  --add-dir "$REPO_DIR" > "$tmp_output"; then
  mv "$tmp_output" "$OUTPUT_FILE"
  trap - EXIT
  echo "Output saved to $OUTPUT_FILE"
else
  echo "Analysis failed; output was not replaced." >&2
  exit 1
fi
