#!/usr/bin/env bash
# capture-label.sh
# UserPromptSubmit hook. Intercepts "#label ..." messages and stores a
# per-session task label keyed by session_id, so statusline.sh can show
# which task each open Claude window is working on.
#
# Usage (typed as a normal chat message):
#   #label EXEC: connector soft-disconnect
#   #label clear            -> removes the label (falls back to auto)
#
# The prompt never reaches Claude (exit 2 blocks it -> 0 tokens).
# Any other prompt passes through untouched.

set -uo pipefail

LABEL_DIR="${HOME}/.claude/statusline/labels"

INPUT=$(cat)

if ! command -v jq >/dev/null 2>&1; then
  exit 0  # no jq: let the prompt pass through, do nothing
fi

PROMPT=$(echo "$INPUT" | jq -r '.prompt // ""')
SID=$(echo "$INPUT" | jq -r '.session_id // ""')

# Only react to messages starting with "#label" (allow leading whitespace).
case "$PROMPT" in
  *[!$' \t']*) ;; # non-empty after trim, continue
esac

TRIMMED="${PROMPT#"${PROMPT%%[![:space:]]*}"}"   # ltrim
case "$TRIMMED" in
  '#label'|'#label '*)
    ;;
  *)
    exit 0  # not a label command -> pass through unchanged
    ;;
esac

if [[ -z "$SID" ]]; then
  echo "#label: session_id unavailable, cannot store label." >&2
  exit 2
fi

mkdir -p "$LABEL_DIR"
LABEL_FILE="${LABEL_DIR}/${SID}"

# Strip the "#label" keyword, then trim surrounding whitespace.
VALUE="${TRIMMED#'#label'}"
VALUE="${VALUE#"${VALUE%%[![:space:]]*}"}"
VALUE="${VALUE%"${VALUE##*[![:space:]]}"}"

if [[ -z "$VALUE" || "$VALUE" == "clear" || "$VALUE" == "-" ]]; then
  rm -f "$LABEL_FILE"
  echo "✓ label cleared (statusline falls back to auto)." >&2
  exit 2
fi

printf '%s' "$VALUE" > "$LABEL_FILE"
echo "✓ label set: ${VALUE}" >&2
exit 2
