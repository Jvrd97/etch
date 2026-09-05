#!/usr/bin/env bash
# [review:need-review] 2026-07-14-night-triage#session-4
# summary: thin wrapper — pipes hook stdin JSON into guard_clickup_task.py (heredoc would swallow stdin)
set -euo pipefail
exec python3 "$(dirname "$0")/guard_clickup_task.py"
