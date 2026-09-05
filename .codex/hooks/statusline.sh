#!/usr/bin/env bash
# statusline.sh
# Reads JSON from stdin, prints status line.
# Schema: https://docs.claude.com/en/docs/claude-code/statusline

set -uo pipefail

INPUT=$(cat)

if ! command -v jq >/dev/null 2>&1; then
  BRANCH=$(git branch --show-current 2>/dev/null || echo "?")
  echo "[$BRANCH] (install jq for full statusline)"
  exit 0
fi

# Extract fields per actual Claude Code schema
MODEL=$(echo "$INPUT" | jq -r '.model.display_name // "?"')
SID=$(echo "$INPUT" | jq -r '.session_id // ""')
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // ""')
PCT=$(echo "$INPUT" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
LIMIT=$(echo "$INPUT" | jq -r '.context_window.context_window_size // 200000')
COST=$(echo "$INPUT" | jq -r '.cost.total_cost_usd // 0')
RATE_PCT=$(echo "$INPUT" | jq -r '.rate_limits.five_hour.used_percentage // 0' | cut -d. -f1)

# Git branch
BRANCH=$(git branch --show-current 2>/dev/null || echo "?")

# ---- Task label + mode tag (per-session disambiguation) ----
# Manual label (set via `#label ...`, see capture-label.sh) wins; otherwise
# fall back to the first substantive user prompt from the transcript.
LABEL_DIR="${HOME}/.claude/statusline/labels"
LABEL_MAX=42
LABEL=""
LABEL_AUTO=0

if [[ -n "$SID" && -f "${LABEL_DIR}/${SID}" ]]; then
  LABEL=$(tr -d '\n' < "${LABEL_DIR}/${SID}")
elif [[ -n "$TRANSCRIPT" && -f "$TRANSCRIPT" ]]; then
  # First user message that is real prose (skip slash-commands, tool results,
  # caveats, command wrappers, system reminders). Bound work with head.
  LABEL=$(head -n 120 "$TRANSCRIPT" 2>/dev/null \
    | jq -rc 'select(.type=="user" and (.message.role=="user"))
        | (.message.content | if type=="string" then . else (map(select(.type=="text")|.text)|join(" ")) end)' 2>/dev/null \
    | sed 's/^[[:space:]]*//' \
    | grep -vaE '^$|^<|^tool_result|^Caveat:|^Shell cwd was reset' \
    | head -n 1)
  LABEL_AUTO=1
fi

# Mode tag: did this session invoke a grill command/skill?
MODE_TAG=""
if [[ -n "$TRANSCRIPT" && -f "$TRANSCRIPT" ]]; then
  # Match an actual invocation only (slash-command wrapper or Skill tool input),
  # NOT a mere mention of "grill" in the injected skills catalog / reminders.
  if grep -qaE '<command-(name|message)>/?(grill-me|grill-me-arch)|"skill"[[:space:]]*:[[:space:]]*"(grill-me|grill-me-arch|architecture-grill)"' "$TRANSCRIPT" 2>/dev/null; then
    MODE_TAG="🔬GRILL"
  else
    MODE_TAG="🔨EXEC"
  fi
fi

# Strip a redundant leading GRILL:/EXEC: from manual labels (tag already shown).
LABEL=$(printf '%s' "$LABEL" | sed -E 's/^[[:space:]]*(GRILL|EXEC)[:[:space:]]+//I')

# Truncate label for display.
if [[ -n "$LABEL" ]]; then
  if (( ${#LABEL} > LABEL_MAX )); then
    LABEL="${LABEL:0:LABEL_MAX}…"
  fi
  [[ "$LABEL_AUTO" -eq 1 ]] && LABEL="~${LABEL}"   # ~ marks an auto-derived label
fi

# Assemble the task segment: "🔨EXEC · connector soft-disconnect ┊ "
TASK_SEG=""
if [[ -n "$MODE_TAG" || -n "$LABEL" ]]; then
  if [[ -n "$LABEL" ]]; then
    TASK_SEG="${MODE_TAG} · ${LABEL} ┊ "
  else
    TASK_SEG="${MODE_TAG} ┊ "
  fi
fi

# Format limit (k/m suffix)
if [[ "$LIMIT" -ge 1000000 ]]; then
  LIMIT_FMT="$(( LIMIT / 1000000 ))M"
else
  LIMIT_FMT="$(( LIMIT / 1000 ))k"
fi

# Format cost
COST_FMT=$(printf '%.2f' "$COST" 2>/dev/null || echo "0.00")

# Smart Zone indicator (based on % used)
if [[ "$PCT" -lt 50 ]]; then
  ZONE="✅ SMART"
elif [[ "$PCT" -lt 75 ]]; then
  ZONE="⚠️  TRANSIT"
else
  ZONE="🔴 DUMB - /clear"
fi

# Rate limit warning
RATE_WARN=""
if [[ "$RATE_PCT" -ge 80 ]]; then
  RATE_WARN=" | 🚨 rate ${RATE_PCT}%"
elif [[ "$RATE_PCT" -ge 60 ]]; then
  RATE_WARN=" | ⚡ rate ${RATE_PCT}%"
fi

echo "${TASK_SEG}[$BRANCH] $MODEL | ctx ${PCT}%/${LIMIT_FMT} $ZONE | \$${COST_FMT}${RATE_WARN}"
