#!/usr/bin/env bash
# backup-before-compact.sh
# Runs before /compact. Saves a snapshot of the transcript so user can /clear
# instead and reload critical context if compact loses something important.

set -uo pipefail

BACKUP_DIR=".claude/backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_FILE="$BACKUP_DIR/pre-compact-$TIMESTAMP.md"

# The transcript is available in stdin via JSON
INPUT=$(cat)

if command -v jq >/dev/null 2>&1; then
  echo "$INPUT" | jq -r '.transcript // empty' >"$BACKUP_FILE" 2>/dev/null || true
else
  echo "$INPUT" >"$BACKUP_FILE"
fi

if [[ -s "$BACKUP_FILE" ]]; then
  cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreCompact",
    "additionalContext": "Transcript backed up to $BACKUP_FILE — consider /clear instead of /compact and reload only what matters."
  }
}
EOF
fi

# Cleanup: keep only last 10 backups
ls -1t "$BACKUP_DIR"/pre-compact-*.md 2>/dev/null | tail -n +11 | xargs -r rm -f

exit 0
