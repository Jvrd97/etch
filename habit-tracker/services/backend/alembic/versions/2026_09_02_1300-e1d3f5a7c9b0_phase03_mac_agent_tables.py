"""phase03_mac_agent_tables — семь таблиц темы macOS-агента одной ревизией

Схемный слой ADR-0019 целиком: `tracked_app`, `title_rule`, `activity_interval`,
`mode_schedule`, `day_mode`, `agent_heartbeat`, `claude_session`. Одна ревизия
вместо семи — так решает ADR и `#155`: цепочка Alembic остаётся линейной, а
тикеты темы после неё пишут код, а не миграции.

Заведена в ветке `fast-4` тикетом `#135` (разметка интервалов в минуты ролей),
потому что `#135`, `#158` и `#160` все стоят на этих таблицах, а схемного слоя
`#155` в ветке нет. Заявка объявлена на доске роя до реализации.

Три вещи, которые здесь несут смысл, а не просто занимают колонку.

`activity_interval.duration_seconds` — `GENERATED ALWAYS ... STORED`: длительность
есть следствие границ, и колонка, которую можно записать, однажды с ними
разойдётся. Записать её напрямую Postgres не даст.

`uq_activity_interval_natural (source, started_at, app_id)` — цель
`ON CONFLICT DO UPDATE`. Повторная присылка пачки после обрыва перезаписывает
строки и ничего не удваивает, поэтому агентскому потоку `Idempotency-Key` не
нужен. У ручной записи `app_id IS NULL`, а NULL в уникальном ключе Postgres
различны — две ручные записи с одинаковым началом не схлопываются, и не должны.

`title_policy` по умолчанию `drop`, и сид `title_rule` начинается с запретов:
менеджер паролей, связка ключей, банк и медицина. Новое приложение не может
принести имя документа тем, что просто появилось.

Сиды — в теле ревизии, как `SEED_METRICS` в контуре health. Расписание режимов
взято из `personal-os/config.md`: пн, вт, ср, пт, сб — `work`; чт и вс —
`dayoff`; `nocode` у вт и чт.

Обратимость полная: `downgrade()` роняет таблицы в обратном порядке, вместе с
сидами. Ничего, кроме них, не трогается.

Revision ID: e1d3f5a7c9b0
Revises: d0c2e4a6b8f1
Create Date: 2026-09-02 13:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1d3f5a7c9b0"
down_revision: Union[str, None] = "d0c2e4a6b8f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Дословный близнец `app.models.activity.DURATION_EXPR`.
DURATION_EXPR = "EXTRACT(EPOCH FROM (ended_at - started_at))::int"

# Расписание режимов по `personal-os/config.md`. 0 = воскресенье … 6 = суббота.
SEED_SCHEDULE: tuple[tuple[int, str, bool], ...] = (
    (0, "dayoff", False),
    (1, "work", False),
    (2, "work", True),
    (3, "work", False),
    (4, "dayoff", True),
    (5, "work", False),
    (6, "work", False),
)

# Правила заголовков, в порядке применения: первое совпавшее выигрывает.
# Сначала запреты — их обойти нельзя ничем, что придёт ниже.
SEED_TITLE_RULES: tuple[tuple[int, str, str, str, str], ...] = (
    (10, "bundle_prefix", "com.1password", "drop", "менеджер паролей"),
    (20, "bundle_id", "com.apple.keychainaccess", "drop", "связка ключей"),
    (30, "bundle_prefix", "com.apple.Health", "drop", "медицина"),
    (40, "bundle_prefix", "de.dkb", "drop", "банк"),
    (50, "bundle_prefix", "com.google.Chrome", "mask", "от заголовка остаётся домен"),
    (60, "bundle_prefix", "com.apple.Safari", "mask", "от заголовка остаётся домен"),
    (
        70,
        "bundle_prefix",
        "com.microsoft.VSCode",
        "mask",
        "остаётся расширение файла и имя репозитория",
    ),
    (80, "bundle_id", "com.apple.dt.Xcode", "mask", "то же, что у редактора"),
)

# Каталог приложений, с которого система начинает. `title_policy` строки должна
# совпадать с действием правила выше: правило применяется на маке, каталог — то,
# что видит сервер, и разойтись им нельзя.
SEED_APPS: tuple[tuple[str, str, str, str], ...] = (
    ("com.microsoft.VSCode", "VS Code", "code", "mask"),
    ("com.apple.dt.Xcode", "Xcode", "code", "mask"),
    ("com.apple.Terminal", "Terminal", "terminal", "drop"),
    ("com.googlecode.iterm2", "iTerm2", "terminal", "drop"),
    ("com.google.Chrome", "Chrome", "browser", "mask"),
    ("com.apple.Safari", "Safari", "browser", "mask"),
    ("com.tinyspeck.slackmacgap", "Slack", "comms", "drop"),
    ("com.hnc.Discord", "Discord", "comms", "drop"),
    ("com.figma.Desktop", "Figma", "design", "drop"),
)


def upgrade() -> None:
    op.create_table(
        "tracked_app",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bundle_id", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column(
            "category", sa.String(length=30), server_default="other", nullable=False
        ),
        sa.Column(
            "title_policy", sa.String(length=10), server_default="drop", nullable=False
        ),
        sa.Column("is_work", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tracked_app_id", "tracked_app", ["id"])
    op.create_index("ix_tracked_app_bundle_id", "tracked_app", ["bundle_id"], unique=True)

    op.create_table(
        "title_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("match_kind", sa.String(length=20), nullable=False),
        sa.Column("pattern", sa.String(length=300), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "match_kind IN ('bundle_id', 'bundle_prefix', 'title_regex')",
            name="ck_title_rule_match_kind",
        ),
        sa.CheckConstraint(
            "action IN ('keep', 'mask', 'drop')", name="ck_title_rule_action"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_title_rule_id", "title_rule", ["id"])
    op.create_index("ix_title_rule_ord", "title_rule", ["ord"])

    op.create_table(
        "activity_interval",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "source", sa.String(length=10), server_default="agent", nullable=False
        ),
        sa.Column("app_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "duration_seconds",
            sa.Integer(),
            sa.Computed(DURATION_EXPR, persisted=True),
            nullable=False,
        ),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column(
            "utc_offset_minutes", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "title_source",
            sa.String(length=10),
            server_default="dropped",
            nullable=False,
        ),
        sa.Column("idle_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("switch_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("plan_task_id", sa.BigInteger(), nullable=True),
        sa.Column("clickup_task_id", sa.String(length=40), nullable=True),
        sa.Column(
            "is_corrected", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ended_at >= started_at", name="ck_activity_interval_forward"
        ),
        sa.CheckConstraint(
            "source IN ('agent', 'manual')", name="ck_activity_interval_source"
        ),
        sa.CheckConstraint(
            "title_source IN ('full', 'masked', 'dropped')",
            name="ck_activity_interval_title_source",
        ),
        sa.ForeignKeyConstraint(["app_id"], ["tracked_app.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source", "started_at", "app_id", name="uq_activity_interval_natural"
        ),
    )
    op.create_index("ix_activity_interval_id", "activity_interval", ["id"])
    op.create_index(
        "ix_activity_interval_local_date", "activity_interval", ["local_date"]
    )
    op.create_index(
        "ix_activity_interval_day_app", "activity_interval", ["local_date", "app_id"]
    )
    op.create_index("ix_activity_interval_task", "activity_interval", ["plan_task_id"])
    op.create_index(
        "ix_activity_interval_day_start",
        "activity_interval",
        ["local_date", "started_at"],
    )

    op.create_table(
        "mode_schedule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("nocode", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_mode_schedule_weekday"),
        sa.CheckConstraint(
            "kind IN ('work', 'dayoff', 'vacation', 'sick')",
            name="ck_mode_schedule_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("weekday"),
    )
    op.create_index("ix_mode_schedule_id", "mode_schedule", ["id"])

    op.create_table(
        "day_mode",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("nocode", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "source", sa.String(length=10), server_default="manual", nullable=False
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('work', 'dayoff', 'vacation', 'sick')", name="ck_day_mode_kind"
        ),
        sa.CheckConstraint(
            "source IN ('schedule', 'manual')", name="ck_day_mode_source"
        ),
        sa.PrimaryKeyConstraint("date"),
    )

    op.create_table(
        "agent_heartbeat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("agent_version", sa.String(length=20), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "accessibility_granted",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "titles_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "sampling_seconds", sa.Integer(), server_default="5", nullable=False
        ),
        sa.Column("queue_depth", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_flush_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_heartbeat_id", "agent_heartbeat", ["id"])
    op.create_index(
        "ix_agent_heartbeat_agent_id", "agent_heartbeat", ["agent_id"], unique=True
    )

    op.create_table(
        "claude_session",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("session_uid", sa.String(length=64), nullable=False),
        sa.Column("cwd", sa.String(length=300), nullable=False),
        sa.Column("git_branch", sa.String(length=120), nullable=True),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assistant_turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("user_turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "cache_read_tokens", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "cache_creation_tokens", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("models", sa.String(length=200), server_default="", nullable=False),
        sa.Column("goal_title", sa.String(length=200), nullable=True),
        sa.Column("cli_version", sa.String(length=20), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claude_session_id", "claude_session", ["id"])
    op.create_index(
        "ix_claude_session_session_uid", "claude_session", ["session_uid"], unique=True
    )
    op.create_index("ix_claude_session_local_date", "claude_session", ["local_date"])

    _seed()


def _seed() -> None:
    """Расписание режимов, правила заголовков и каталог приложений."""
    schedule = sa.table(
        "mode_schedule",
        sa.column("weekday", sa.SmallInteger),
        sa.column("kind", sa.String),
        sa.column("nocode", sa.Boolean),
    )
    op.bulk_insert(
        schedule,
        [
            {"weekday": weekday, "kind": kind, "nocode": nocode}
            for weekday, kind, nocode in SEED_SCHEDULE
        ],
    )

    rules = sa.table(
        "title_rule",
        sa.column("ord", sa.Integer),
        sa.column("match_kind", sa.String),
        sa.column("pattern", sa.String),
        sa.column("action", sa.String),
        sa.column("note", sa.Text),
    )
    op.bulk_insert(
        rules,
        [
            {
                "ord": ord_,
                "match_kind": match_kind,
                "pattern": pattern,
                "action": action,
                "note": note,
            }
            for ord_, match_kind, pattern, action, note in SEED_TITLE_RULES
        ],
    )

    apps = sa.table(
        "tracked_app",
        sa.column("bundle_id", sa.String),
        sa.column("display_name", sa.String),
        sa.column("category", sa.String),
        sa.column("title_policy", sa.String),
    )
    op.bulk_insert(
        apps,
        [
            {
                "bundle_id": bundle_id,
                "display_name": display_name,
                "category": category,
                "title_policy": title_policy,
            }
            for bundle_id, display_name, category, title_policy in SEED_APPS
        ],
    )


def downgrade() -> None:
    op.drop_table("claude_session")
    op.drop_table("agent_heartbeat")
    op.drop_table("day_mode")
    op.drop_table("mode_schedule")
    op.drop_table("activity_interval")
    op.drop_table("title_rule")
    op.drop_table("tracked_app")
