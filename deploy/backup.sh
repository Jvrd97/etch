#!/usr/bin/env bash
# [review:need-review] PHASE-03/96
# summary: daily pg_dump written atomically, rotation by age with a floor under how few dumps may remain, and a status file that turns a silent cron failure into a visible one
#
# Cron on the VPS:
#   0 3 * * * /opt/habit-tracker/deploy/backup.sh >> /var/log/habit-backup.log 2>&1
#
# Since PHASE-03/88 the database is the only copy of a day: the marks stopped
# living in git the moment they stopped living in `.html`. That is why this
# script is a condition of operation rather than a nicety, and why each of its
# three failure modes is loud:
#
#   * a dump that never ran      -> the STATUS file says FAIL and the exit code
#                                   is non-zero;
#   * a dump that ran and lied   -> the stream is written to `.partial` and only
#                                   renamed once `gzip -t` accepts it, so a
#                                   truncated dump never takes the name of a
#                                   backup;
#   * a rotation that ate the    -> deletion is bounded by MIN_KEEP: a month of
#     last surviving dump           broken cron cannot leave the directory empty.
#
# Restoring one is `deploy/restore-check.sh`; the human procedure is in
# `deploy/README.md`, section «Что делать, когда база потеряна».
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/habit-tracker/backups}"
# Dumps older than this are rotated out. Daily cron => fourteen dumps.
KEEP_DAYS="${KEEP_DAYS:-14}"
# ...but never fewer than this many, whatever their age. Age-only rotation
# empties the directory after two weeks of a cron job nobody noticed had died,
# which is exactly when the backups are needed.
MIN_KEEP="${MIN_KEEP:-3}"
# Floor on the *uncompressed* stream. Compressed size says nothing: a dump of
# two hundred repeated statements gzips to sixty-six bytes, and so would half a
# database.
MIN_BYTES="${MIN_BYTES:-1024}"
# The last line `pg_dump` writes. Its absence is what a stream cut halfway looks
# like, and no size check catches that — a dump truncated at 80% is still large.
DUMP_TRAILER="${DUMP_TRAILER:-PostgreSQL database dump complete}"
STATUS_FILE="${STATUS_FILE:-$BACKUP_DIR/backup-status}"
# Overridable so the tests can drive the script without docker or postgres.
DUMP_CMD="${DUMP_CMD:-docker exec habit_postgres pg_dump -U habit_user habit_tracker}"

STAGE="startup"
TMP=""

write_status() {
  # Written on every run, success or failure. `restore-check.sh` reads it, and
  # so does a human at three in the morning who wants one file to look at.
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" >"$STATUS_FILE" || true
}

on_exit() {
  code=$?
  if [ "$code" -ne 0 ]; then
    if [ -n "$TMP" ]; then
      rm -f -- "$TMP"
    fi
    write_status "FAIL" "stage=$STAGE exit=$code"
    echo "backup FAILED at stage '$STAGE' (exit $code); status: $STATUS_FILE" >&2
  fi
  exit "$code"
}
trap on_exit EXIT

mkdir -p "$BACKUP_DIR"

STAGE="dump"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
TARGET="$BACKUP_DIR/habit_tracker_$STAMP.sql.gz"
TMP="$TARGET.partial"

# `.partial` first, rename last. A dump that dies halfway then leaves a file
# whose name says so, instead of a plausible-looking archive that restores into
# half a database.
# shellcheck disable=SC2086 # DUMP_CMD is a command line; splitting is the point
$DUMP_CMD | gzip >"$TMP"

STAGE="verify"
if ! gzip -t "$TMP" 2>/dev/null; then
  echo "dump is not a readable gzip stream: $TMP" >&2
  exit 1
fi
SIZE="$(gzip -dc "$TMP" | wc -c | tr -d '[:space:]')"
if [ "$SIZE" -lt "$MIN_BYTES" ]; then
  echo "dump is $SIZE bytes uncompressed, below the $MIN_BYTES floor: $TMP" >&2
  exit 1
fi
if ! gzip -dc "$TMP" | tail -n 5 | grep -q -- "$DUMP_TRAILER"; then
  echo "dump does not end with '$DUMP_TRAILER' — the stream was cut: $TMP" >&2
  exit 1
fi
mv -- "$TMP" "$TARGET"
TMP=""

STAGE="rotate"
# Names carry `YYYY-MM-DD_HHMMSS`, so a reverse lexicographic sort is a reverse
# chronological one and needs no `ls -t`, whose output is unsafe to parse.
index=0
while IFS= read -r dump; do
  if [ -z "$dump" ]; then
    continue
  fi
  index=$((index + 1))
  if [ "$index" -le "$MIN_KEEP" ]; then
    continue
  fi
  if [ -n "$(find "$dump" -mtime +"$KEEP_DAYS" -print -quit 2>/dev/null)" ]; then
    rm -f -- "$dump"
    echo "rotated out: $dump"
  fi
done <<EOF
$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'habit_tracker_*.sql.gz' | sort -r)
EOF

STAGE="done"
write_status "OK" "file=$TARGET bytes=$SIZE"
echo "backup done: $TARGET ($SIZE bytes uncompressed)"
