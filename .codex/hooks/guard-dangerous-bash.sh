#!/usr/bin/env bash
# guard-dangerous-bash.sh
# Runs before every Bash tool invocation. Blocks patterns that static permissions
# can't reliably catch (e.g., chained commands, encoded payloads).
#
# Reads JSON from stdin with shape:
#   { "tool_input": { "command": "..." }, ... }
#
# Output: JSON to stdout to allow/deny/modify. Exit 0 = continue with default.

set -euo pipefail

# Read the JSON input from stdin
INPUT=$(cat)

# Extract command (fall back gracefully if jq not available)
if command -v jq >/dev/null 2>&1; then
  CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
else
  # Crude fallback
  CMD=$(echo "$INPUT" | grep -oP '"command"\s*:\s*"\K[^"]+' | head -1 || echo "")
fi

# Empty command - let Claude Code handle it
if [[ -z "$CMD" ]]; then
  exit 0
fi

# List of forbidden patterns (regex)
DANGEROUS_PATTERNS=(
  'rm\s+-rf\s+/'
  'rm\s+-rf\s+~'
  'rm\s+-rf\s+\$HOME'
  '>\s*/dev/sda'
  'dd\s+if=.*of=/dev/'
  ':\(\)\{.*:\|:'                          # fork bomb
  'mkfs\.'
  'chmod\s+-R\s+777\s+/'
  'curl[^|]*\|\s*(sh|bash|zsh)'
  'wget[^|]*\|\s*(sh|bash|zsh)'
  'eval\s*\$\(curl'
  'git\s+push\s+(-f|--force)'
  'git\s+reset\s+--hard\s+origin'
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if echo "$CMD" | grep -Eq "$pattern"; then
    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Blocked by guard-dangerous-bash.sh: command matches forbidden pattern '$pattern'. If this is intentional, run it manually outside Claude."
  }
}
EOF
    exit 0
  fi
done

# All clear
exit 0
