#!/usr/bin/env bash
# format-on-save.sh
# Runs after Write/Edit/MultiEdit. Auto-formats based on file extension.
# Non-blocking: failures are logged but don't fail the hook.

set -uo pipefail

FILE_PATH="${1:-}"

# Empty path - nothing to do
if [[ -z "$FILE_PATH" ]] || [[ ! -f "$FILE_PATH" ]]; then
  exit 0
fi

LOG_FILE=".claude/logs/format-on-save.log"
mkdir -p "$(dirname "$LOG_FILE")"

format() {
  local cmd="$1"
  local target="$2"
  if command -v "${cmd%% *}" >/dev/null 2>&1; then
    eval "$cmd \"$target\"" >>"$LOG_FILE" 2>&1 || \
      echo "[$(date -u +%FT%TZ)] $cmd failed for $target" >>"$LOG_FILE"
  fi
}

case "$FILE_PATH" in
  *.py)
    format "ruff format" "$FILE_PATH"
    format "ruff check --fix" "$FILE_PATH"
    ;;
  *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs)
    format "npx --no-install prettier --write" "$FILE_PATH"
    ;;
  *.json|*.jsonc)
    format "npx --no-install prettier --write" "$FILE_PATH"
    ;;
  *.md|*.mdx)
    format "npx --no-install prettier --write" "$FILE_PATH"
    ;;
  *.go)
    format "gofmt -w" "$FILE_PATH"
    ;;
  *.rs)
    format "rustfmt" "$FILE_PATH"
    ;;
  *.sh)
    format "shfmt -w" "$FILE_PATH"
    ;;
esac

exit 0
