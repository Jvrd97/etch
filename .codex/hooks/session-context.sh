#!/usr/bin/env bash
# session-context.sh
# Runs at session start. Injects minimal but useful project state into context.
# Stays small to preserve Smart Zone budget.

set -uo pipefail

OUTPUT=""

# Current branch
if git rev-parse --git-dir >/dev/null 2>&1; then
  BRANCH=$(git branch --show-current 2>/dev/null || echo "(detached)")
  OUTPUT+="Branch: $BRANCH\n"

  # Last 3 commits
  COMMITS=$(git log -3 --oneline 2>/dev/null || echo "")
  if [[ -n "$COMMITS" ]]; then
    OUTPUT+="Recent commits:\n$COMMITS\n"
  fi

  # Uncommitted changes count
  CHANGED_COUNT=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$CHANGED_COUNT" -gt 0 ]]; then
    OUTPUT+="Uncommitted changes: $CHANGED_COUNT files\n"
  fi
fi

# Active issues from local issues/ dir (if exists)
if [[ -d "issues" ]]; then
  OPEN=$(find issues -maxdepth 2 -name "*.md" -not -path "*/closed/*" 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$OPEN" -gt 0 ]]; then
    OUTPUT+="Open local issues: $OPEN (in ./issues/)\n"
  fi
fi

if [[ -n "$OUTPUT" ]]; then
  cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Project state at session start:\n$OUTPUT"
  }
}
EOF
fi

exit 0
