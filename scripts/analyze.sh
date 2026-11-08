#!/usr/bin/env bash
# Batch read-only analysis. Results are saved by this script, not by the agent.
# Usage: ./scripts/analyze.sh <project> [batch_size]
set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
"$PROJ_DIR/scripts/setup.sh"

PROJECT="${1:?Usage: $0 <project> [batch_size]}"
BATCH_SIZE="${2:-5}"
TEMPLATE="$PROJ_DIR/prompts/analyze_query.txt"
QUERY_FILE="$PROJ_DIR/data/queries/${PROJECT}-queries.txt"
OUTPUT_DIR="$PROJ_DIR/data/outputs/$PROJECT"
REPO_DIR="$PROJ_DIR/data/repos/$PROJECT"

if [[ ! "$PROJECT" =~ ^[A-Za-z0-9._-]+$ ]] || [[ "$PROJECT" == "." || "$PROJECT" == ".." ]]; then
  echo "ERROR: project must be a simple directory name." >&2
  exit 2
fi
if ! [[ "$BATCH_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: batch_size must be a positive integer." >&2
  exit 2
fi
if [ ! -d "$REPO_DIR" ]; then
  echo "ERROR: repository directory not found: $REPO_DIR" >&2
  exit 1
fi
if [ ! -f "$QUERY_FILE" ]; then
  echo "ERROR: query file not found: $QUERY_FILE" >&2
  exit 1
fi

export NEXTORCA_WORKSPACE_ROOT="$REPO_DIR"
source "$PROJ_DIR/scripts/start_services.sh"

mkdir -p "$OUTPUT_DIR"
PROMPT_TPL="$(cat "$TEMPLATE")"

IDS=()
QUESTIONS=()
while IFS=$'\t' read -r id query; do
  [ -z "$id" ] && continue
  if ! [[ "$id" =~ ^[0-9]+$ ]]; then
    echo "ERROR: query ID must be numeric: $id" >&2
    exit 2
  fi
  IDS+=("$id")
  QUESTIONS+=("$query")
done < "$QUERY_FILE"

echo "Project: $PROJECT"
echo "Total queries: ${#QUESTIONS[@]}, batch size: $BATCH_SIZE"
echo "Permission mode: plan (read-only)"

success=0
skipped=0
failed=0

for ((i=0; i<${#QUESTIONS[@]}; i+=BATCH_SIZE)); do
  batch_num=$(( i/BATCH_SIZE + 1 ))
  echo "=== Batch $batch_num (q$((i+1))-q$((i+BATCH_SIZE))) ==="
  pids=()

  for ((j=i; j<i+BATCH_SIZE && j<${#QUESTIONS[@]}; j++)); do
    id="${IDS[$j]}"
    printf -v num '%03d' "$id"
    question="${QUESTIONS[$j]}"
    output_file="$OUTPUT_DIR/q${num}.md"

    if [ -f "$output_file" ]; then
      skipped=$((skipped + 1))
      continue
    fi

    prompt="${PROMPT_TPL//\{project\}/$PROJECT}"
    prompt="${prompt//\{question\}/$question}"

    (
      cd "$PROJ_DIR"
      tmp_output="$(mktemp "$OUTPUT_DIR/.q${num}.XXXXXX")"
      trap 'rm -f "$tmp_output"' EXIT
      if printf '%s\n' "$prompt" | claude -p \
        --permission-mode plan \
        --model sonnet \
        --add-dir "$REPO_DIR" > "$tmp_output"; then
        mv "$tmp_output" "$output_file"
        trap - EXIT
        echo "  ✓ q${num} done"
      else
        echo "  ✗ q${num} failed" >&2
        exit 1
      fi
    ) &
    pids+=($!)
  done

  for pid in "${pids[@]+"${pids[@]}"}"; do
    [ -z "$pid" ] && continue
    if wait "$pid"; then
      success=$((success + 1))
    else
      failed=$((failed + 1))
    fi
  done
  echo "=== Batch $batch_num complete ==="
done

echo ""
echo "Project: $PROJECT"
echo "Success: $success, Skipped: $skipped, Failed: $failed"
echo "Outputs in data/outputs/$PROJECT/"
