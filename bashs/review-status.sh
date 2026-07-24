#!/usr/bin/env bash
# [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
# summary: counts need-review vs approved markers across tracked files; exits non-zero while anything is still unreviewed
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Concatenated so this script's own source does not match the tokens it scans
# for — otherwise it would count itself as unreviewed forever.
NEED_TOKEN="[review:""need-review]"
APPROVED_TOKEN="[review:""approved]"

# Only tracked files: untracked build output and vendored deps must not skew the
# count. Markdown is excluded because CLAUDE.md and the command docs spell the
# marker tokens out literally and would otherwise be counted as unreviewed code.
# `.claude/` is excluded for the same reason one level deeper: the harness
# scripts there discuss the markers in prose, so they would pin the count above
# zero forever and the exit code would never go green.
list_files() {
  git ls-files -z -- ':!:*.md' ':!:.claude/'
}

# A file's status is its FIRST marker — the header one. Later occurrences (a
# doc-comment quoting a token, a test fixture) must not put one file into both
# buckets.
first_marker() {
  grep -m1 -o -F -e "$NEED_TOKEN" -e "$APPROVED_TOKEN" -- "$1" 2>/dev/null || true
}

need_files=''
approved_files=''

# `case` is not used here: the tokens contain brackets, which a case pattern
# would read as a character class instead of literal text.
while IFS= read -r -d '' file; do
  marker="$(first_marker "$file")"
  if [ "$marker" = "$NEED_TOKEN" ]; then
    need_files+="$file"$'\n'
  elif [ "$marker" = "$APPROVED_TOKEN" ]; then
    approved_files+="$file"$'\n'
  fi
done < <(list_files)

count_lines() {
  if [ -z "$1" ]; then
    printf '0'
  else
    printf '%s' "$1" | grep -c '' | tr -d ' '
  fi
}

need_count="$(count_lines "$need_files")"
approved_count="$(count_lines "$approved_files")"

printf 'review-status (%s)\n' "$REPO_ROOT"
printf '  need-review: %s\n' "$need_count"
printf '  approved:    %s\n' "$approved_count"

if [ "$need_count" -gt 0 ]; then
  printf '\nfiles awaiting review:\n'
  printf '%s' "$need_files" | sed 's/^/  /'
  exit 1
fi

printf '\nall marked files are approved\n'
exit 0
