"""
Tests for `deploy/backup.sh` and `deploy/restore-check.sh`.

Shell, not python, and outside this service — but this is the only test runner
the repository has, and the alternative is a backup whose failure modes are
verified by reading. Every case here is one of the ways a backup has actually
betrayed somebody: the dump command failed and left a plausible-looking file,
the rotation ate the last surviving dump, the restore check passed on a dump
that restores nothing, a credential ended up inside the archive.

Neither docker nor postgres is needed: both scripts take their outside world
through overridable command lines (`DUMP_CMD`, `PSQL_CMD`), and the tests hand
them fakes.
"""

# [review:need-review] PHASE-03/96
# summary: the deploy scripts driven with stubbed pg_dump/psql — atomic write, the floor under rotation, the loud failure, and the four refusals of restore-check (stale, corrupt, secret-carrying, empty)
import gzip
import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[4] / "deploy"
BACKUP_SH = DEPLOY / "backup.sh"
RESTORE_CHECK_SH = DEPLOY / "restore-check.sh"
EXPORT_MD_SH = DEPLOY / "export-md.sh"

# A dump `backup.sh` accepts: past the 1 KB floor and ending in the trailer
# `pg_dump` writes last, which is what a stream cut halfway does not have.
SAMPLE_SQL = (
    "-- habit_tracker dump\n"
    + ("SELECT 1;\n" * 200)
    + "--\n-- PostgreSQL database dump complete\n--\n"
)

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("gzip") is None,
    reason="the deploy scripts need bash and gzip",
)


def run(script: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run a deploy script with a clean-ish environment and capture everything."""
    environment = dict(os.environ)
    environment.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=environment,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )


def sql_source(directory: Path) -> str:
    """A `DUMP_CMD` that prints sample SQL — the stand-in for `pg_dump`."""
    path = directory / "sample.sql"
    path.write_text(SAMPLE_SQL, encoding="utf-8")
    return f"cat {path}"


def dumps_in(directory: Path) -> list[Path]:
    return sorted(directory.glob("habit_tracker_*.sql.gz"))


def make_dump(path: Path, body: str = SAMPLE_SQL) -> Path:
    """A gzipped dump on disk, as `backup.sh` would have left it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(body.encode("utf-8")))
    return path


def fake_psql(directory: Path, counts: str = "12|9|140|55") -> Path:
    """
    A `psql` that answers every call the way a healthy restore would.

    It swallows the restored SQL on stdin, prints the count row when asked for
    one, and stays silent otherwise — which is exactly the surface
    `restore-check.sh` uses.
    """
    script = directory / "fake-psql.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'echo "$*" >> "$FAKE_PSQL_LOG"\n'
        'if printf "%s" "$*" | grep -q "count(\\*)"; then\n'
        f'  echo "{counts}"\n'
        "else\n"
        "  cat >/dev/null 2>&1 || true\n"
        "fi\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


# --------------------------------------------------------------- backup.sh


def test_a_successful_backup_writes_one_dump_and_an_ok_status(tmp_path: Path) -> None:
    """The everyday case: a dump appears, the status file says OK."""
    backups = tmp_path / "backups"
    result = run(
        BACKUP_SH,
        BACKUP_DIR=str(backups),
        DUMP_CMD=sql_source(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert len(dumps_in(backups)) == 1
    status = (backups / "backup-status").read_text(encoding="utf-8")
    assert status.split()[1] == "OK"
    # The dump is a readable gzip stream carrying the SQL, not an empty file.
    assert b"habit_tracker dump" in gzip.decompress(dumps_in(backups)[0].read_bytes())


def test_a_failed_dump_leaves_no_file_and_says_so(tmp_path: Path) -> None:
    """
    The failure the old script hid: `pg_dump` dies, a `.gz` appears anyway.

    Writing to `.partial` and renaming last is what makes "there is a file
    called habit_tracker_….sql.gz" mean "there is a backup".
    """
    backups = tmp_path / "backups"
    result = run(
        BACKUP_SH,
        BACKUP_DIR=str(backups),
        DUMP_CMD="bash -c 'echo boom >&2; exit 3'",
    )

    assert result.returncode != 0
    assert dumps_in(backups) == []
    assert list(backups.glob("*.partial")) == []
    assert "backup FAILED" in result.stderr
    status = (backups / "backup-status").read_text(encoding="utf-8")
    assert "FAIL" in status
    assert "stage=dump" in status


def test_a_suspiciously_small_dump_is_refused(tmp_path: Path) -> None:
    """An empty database is still bigger than a kilobyte; a truncated pipe is not."""
    backups = tmp_path / "backups"
    result = run(
        BACKUP_SH,
        BACKUP_DIR=str(backups),
        DUMP_CMD="printf ''",
    )

    assert result.returncode != 0
    assert dumps_in(backups) == []
    assert "FAIL" in (backups / "backup-status").read_text(encoding="utf-8")


def test_a_dump_cut_halfway_is_refused(tmp_path: Path) -> None:
    """
    The failure no size check catches: the stream dies at 80% and looks big.

    `pg_dump` writes its trailer last, so a dump without it is a dump that never
    finished — and a file that restores into a database missing whatever came
    after the cut.
    """
    backups = tmp_path / "backups"
    truncated = tmp_path / "truncated.sql"
    truncated.write_text(SAMPLE_SQL.split("-- PostgreSQL")[0], encoding="utf-8")

    result = run(
        BACKUP_SH,
        BACKUP_DIR=str(backups),
        DUMP_CMD=f"cat {truncated}",
    )

    assert result.returncode != 0
    assert dumps_in(backups) == []
    assert "the stream was cut" in result.stderr


def test_rotation_removes_the_old_and_keeps_the_recent(tmp_path: Path) -> None:
    """Dumps past the age limit go; the ones inside it stay."""
    backups = tmp_path / "backups"
    old = make_dump(backups / "habit_tracker_2026-08-01_030000.sql.gz")
    recent = make_dump(backups / "habit_tracker_2026-08-29_030000.sql.gz")
    two_days = 2 * 24 * 3600
    thirty_days = 30 * 24 * 3600
    now = int(old.stat().st_mtime)
    os.utime(old, (now - thirty_days, now - thirty_days))
    os.utime(recent, (now - two_days, now - two_days))

    result = run(
        BACKUP_SH,
        BACKUP_DIR=str(backups),
        MIN_KEEP="1",
        DUMP_CMD=sql_source(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    names = [one.name for one in dumps_in(backups)]
    assert old.name not in names
    assert recent.name in names


def test_rotation_never_empties_the_directory(tmp_path: Path) -> None:
    """
    Two weeks of dead cron must not take the last backups with them.

    Age-only rotation deletes everything exactly when the dumps are needed, so
    `MIN_KEEP` is a floor no age can push through.
    """
    backups = tmp_path / "backups"
    ancient = [
        make_dump(backups / f"habit_tracker_2026-01-0{index}_030000.sql.gz")
        for index in range(1, 5)
    ]
    long_ago = int(ancient[0].stat().st_mtime) - 400 * 24 * 3600
    for one in ancient:
        os.utime(one, (long_ago, long_ago))

    result = run(
        BACKUP_SH,
        BACKUP_DIR=str(backups),
        MIN_KEEP="3",
        DUMP_CMD=sql_source(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    # The fresh dump plus the two newest ancient ones: the floor counts every
    # dump present, the new one included.
    assert len(dumps_in(backups)) == 3


# --------------------------------------------------------- restore-check.sh


def test_restore_check_passes_on_a_dump_that_restores_days(tmp_path: Path) -> None:
    """The healthy path prints the four counts and exits zero."""
    backups = tmp_path / "backups"
    make_dump(backups / "habit_tracker_2026-08-30_030000.sql.gz")
    (backups / "backup-status").write_text("2026-08-30T03:00:00Z OK file=x bytes=9\n")
    psql = fake_psql(tmp_path)

    result = run(
        RESTORE_CHECK_SH,
        BACKUP_DIR=str(backups),
        PSQL_CMD=f"bash {psql}",
        FAKE_PSQL_LOG=str(tmp_path / "psql.log"),
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "restored: days=12 plans=9 items=140 marks=55" in result.stdout
    assert "restore-check OK" in result.stdout
    # The throwaway database is dropped, whatever else happened.
    assert "DROP DATABASE" in (tmp_path / "psql.log").read_text(encoding="utf-8")


def test_restore_check_fails_when_the_restored_database_has_no_days(
    tmp_path: Path,
) -> None:
    """
    The acceptance case: an empty dump exits non-zero.

    `pg_dump` of the wrong database exits zero and produces a perfectly valid
    archive of nothing, which is the failure this check exists for.
    """
    backups = tmp_path / "backups"
    make_dump(backups / "habit_tracker_2026-08-30_030000.sql.gz")
    psql = fake_psql(tmp_path, counts="0|0|0|0")

    result = run(
        RESTORE_CHECK_SH,
        BACKUP_DIR=str(backups),
        PSQL_CMD=f"bash {psql}",
        FAKE_PSQL_LOG=str(tmp_path / "psql.log"),
    )

    assert result.returncode != 0
    assert "no days at all" in result.stderr


def test_restore_check_fails_on_a_broken_dump(tmp_path: Path) -> None:
    """A file that is not a gzip stream is refused before postgres is touched."""
    backups = tmp_path / "backups"
    backups.mkdir(parents=True)
    (backups / "habit_tracker_2026-08-30_030000.sql.gz").write_bytes(b"not gzip at all")
    psql = fake_psql(tmp_path)

    result = run(
        RESTORE_CHECK_SH,
        BACKUP_DIR=str(backups),
        PSQL_CMD=f"bash {psql}",
        FAKE_PSQL_LOG=str(tmp_path / "psql.log"),
    )

    assert result.returncode != 0
    assert "not a readable gzip stream" in result.stderr
    assert not (tmp_path / "psql.log").exists()


def test_restore_check_fails_when_there_is_no_dump_at_all(tmp_path: Path) -> None:
    """An empty backup directory is a failure, not a quiet success."""
    backups = tmp_path / "backups"
    backups.mkdir(parents=True)

    result = run(RESTORE_CHECK_SH, BACKUP_DIR=str(backups))

    assert result.returncode != 0
    assert "no dump" in result.stderr


def test_restore_check_fails_on_a_dump_nobody_refreshed(tmp_path: Path) -> None:
    """
    A dump older than the age limit means the cron job is dead.

    Without this the check would keep passing on last month's archive while
    every day since then quietly stopped being recoverable.
    """
    backups = tmp_path / "backups"
    stale = make_dump(backups / "habit_tracker_2026-07-01_030000.sql.gz")
    long_ago = int(stale.stat().st_mtime) - 10 * 24 * 3600
    os.utime(stale, (long_ago, long_ago))

    result = run(RESTORE_CHECK_SH, BACKUP_DIR=str(backups), MAX_AGE_HOURS="36")

    assert result.returncode != 0
    assert "older than 36 h" in result.stderr


def test_restore_check_fails_when_the_last_backup_recorded_a_failure(
    tmp_path: Path,
) -> None:
    """The status file is read, not just written — that is what closes the loop."""
    backups = tmp_path / "backups"
    make_dump(backups / "habit_tracker_2026-08-30_030000.sql.gz")
    (backups / "backup-status").write_text(
        "2026-08-30T03:00:00Z FAIL stage=dump exit=3\n"
    )

    result = run(RESTORE_CHECK_SH, BACKUP_DIR=str(backups))

    assert result.returncode != 0
    assert "recorded a failure" in result.stderr


def test_a_credential_inside_the_dump_stops_the_check(tmp_path: Path) -> None:
    """
    The acceptance case: no secret may be inside a dump, and it is checked.

    `deploy/README.md` promises the archive holds no credentials; a promise
    nothing verifies is a wish. The value here is a shaped fake, not a token.
    """
    backups = tmp_path / "backups"
    make_dump(
        backups / "habit_tracker_2026-08-30_030000.sql.gz",
        SAMPLE_SQL + "INSERT INTO t VALUES ('ya29.NOTAREALTOKENvalue0001');\n",
    )
    psql = fake_psql(tmp_path)

    result = run(
        RESTORE_CHECK_SH,
        BACKUP_DIR=str(backups),
        PSQL_CMD=f"bash {psql}",
        FAKE_PSQL_LOG=str(tmp_path / "psql.log"),
    )

    assert result.returncode != 0
    assert "credential pattern" in result.stderr
    assert not (tmp_path / "psql.log").exists()


# ------------------------------------------------------------- export-md.sh


def test_export_md_reports_a_failing_exporter(tmp_path: Path) -> None:
    """
    A week that produced nothing is a failure of the archive, not a no-op.

    The exporter exits non-zero when it wrote no files; the wrapper has to carry
    that out to cron rather than swallow it.
    """
    archive = tmp_path / "exports"
    result = run(
        EXPORT_MD_SH,
        ARCHIVE_DIR=str(archive),
        EXPORT_CMD="false",
    )

    assert result.returncode != 0
    assert "export-md FAILED" in result.stderr
    assert "FAIL" in (archive / "export-status").read_text(encoding="utf-8")


def test_export_md_records_the_week_it_wrote(tmp_path: Path) -> None:
    """The happy path leaves one line a human can read a week later."""
    archive = tmp_path / "exports"
    result = run(
        EXPORT_MD_SH,
        ARCHIVE_DIR=str(archive),
        WEEK="2026-W35",
        EXPORT_CMD="echo exporter-called",
    )

    assert result.returncode == 0, result.stderr
    status = (archive / "export-status").read_text(encoding="utf-8")
    assert "OK week=2026-W35" in status
