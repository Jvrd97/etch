#!/usr/bin/env bash
# check-feedback-loops.sh
# Runs on Stop event (turn end). If tests/types are broken, blocks completion
# and tells Claude to fix before stopping. This is the "feedback loops are
# the ceiling" enforcement.
#
# Set CLAUDE_SKIP_FEEDBACK_CHECK=1 to disable (e.g., during pure planning).

set -uo pipefail

# Skip if explicitly disabled or if we're in a planning-only session
if [[ "${CLAUDE_SKIP_FEEDBACK_CHECK:-0}" == "1" ]]; then
  exit 0
fi

# Skip if no source files were modified in this session
# (Heuristic: check if there are uncommitted changes to source dirs)
CHANGED=$(git status --porcelain 2>/dev/null | grep -E "^\s*[MA]\s+(src|app|lib|services|api)/" || true)
if [[ -z "$CHANGED" ]]; then
  exit 0
fi

LOG_FILE=".claude/logs/feedback-loops.log"
mkdir -p "$(dirname "$LOG_FILE")"
echo "[$(date -u +%FT%TZ)] Running feedback checks..." >"$LOG_FILE"

FAILED=()

run_check() {
  local name="$1"
  local cmd="$2"
  echo "--- $name ---" >>"$LOG_FILE"
  if ! eval "$cmd" >>"$LOG_FILE" 2>&1; then
    FAILED+=("$name")
  fi
}

# Detect project type and run relevant checks
if [[ -f "package.json" ]]; then
  if grep -q '"typecheck"' package.json 2>/dev/null; then
    run_check "typecheck" "npm run typecheck --silent"
  elif [[ -f "tsconfig.json" ]]; then
    run_check "typecheck" "npx --no-install tsc --noEmit"
  fi

  if grep -q '"lint"' package.json 2>/dev/null; then
    run_check "lint" "npm run lint --silent"
  fi

  if grep -q '"test"' package.json 2>/dev/null; then
    run_check "test" "npm test --silent -- --run"
  fi
fi

if [[ -f "pyproject.toml" ]] || [[ -f "setup.py" ]]; then
  if command -v ruff >/dev/null 2>&1; then
    run_check "ruff" "ruff check ."
  fi
  if command -v mypy >/dev/null 2>&1 && [[ -f "mypy.ini" || $(grep -l "tool.mypy" pyproject.toml 2>/dev/null) ]]; then
    run_check "mypy" "mypy ."
  fi
  if command -v pytest >/dev/null 2>&1 && [[ -d "tests" || -d "test" ]]; then
    run_check "pytest" "pytest -q"
  fi
fi

if [[ ${#FAILED[@]} -gt 0 ]]; then
  REASON="Feedback loops failed: ${FAILED[*]}. Read .claude/logs/feedback-loops.log for details. Fix these before completing the turn — broken feedback loops mean future agents will code blind."
  cat <<EOF
{
  "decision": "block",
  "reason": "$REASON"
}
EOF
  exit 0
fi

exit 0
