"""plan item editing — who touched the line, when, and the position nobody may duplicate

Три вещи, которых #87 не завёл, потому что план приезжал документом целиком и
правился только заменой.

`edited_by` и `updated_at` отвечают на вопрос «эту строку правил человек или
машина». Без них #150 нечего журналировать, а асимметрия строгости из #147
(машине нарушение блокирует запись, человеку — нет) не имеет опоры в данных.

`uq_plan_item_position` делает позицию уникальной внутри уровня. Уровень — это
`(section_id, parent_id)`: `ord` в #87 нумерует братьев между собой, а не всю
секцию, поэтому уникальность по `(section_id, ord)` была бы ложной — родитель на
позиции 0 и его ребёнок на позиции 0 живут в одной секции законно. `NULLS NOT
DISTINCT` нужен ровно затем, чтобы правило действовало и для корневых пунктов, у
которых `parent_id` пуст (PostgreSQL 15+). `DEFERRABLE INITIALLY DEFERRED` —
чтобы перестановка внутри одной транзакции проходила через промежуточное
состояние с дублями и падала только на коммите, если дубли остались.

Обратимость: ограничение снимается, колонки удаляются. Не возвращаются только
позиции, перенумерованные перед созданием ограничения, — см. `RENUMBER_DUPLICATE_
POSITIONS` ниже.

Revision ID: b2d4f6a8c0e3
Revises: c8f0a2b4d6e7
Create Date: 2026-09-02 09:00:00.000000+00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d4f6a8c0e3"
down_revision: Union[str, None] = "c8f0a2b4d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Кто последним трогал строку. Три значения, а не булев «человек ли»: правка
# скиллом `/day-open` и правка агентом чата — разные источники, и различать их
# придётся раньше, чем кто-нибудь захочет добавить четвёртое.
EDITORS = ("human", "ai", "skill")

# Позиция уникальна внутри уровня. Дословно повторено в `app/models/plan.py`:
# миграция — снимок, и импорт кода приложения сюда сделал бы её зависимой от
# того, как модель выглядит сегодня, а не от того, как выглядела тогда.
POSITION_UNIQUE = (
    "ALTER TABLE plan_item ADD CONSTRAINT uq_plan_item_position "
    "UNIQUE NULLS NOT DISTINCT (section_id, parent_id, ord) "
    "DEFERRABLE INITIALLY DEFERRED"
)

# Дубли позиций гасятся до того, как позиция станет уникальной. С `d9f1b3c5e7a0`
# `ord` не был защищён ничем: импорт исторических дней (`#89`), перенос пункта и
# правка плана руками расставляли номера сами, и на базе с историей внутри одного
# уровня лежат два пункта с одним `ord`. Ограничение ниже на таких данных не
# создаётся — `could not create unique index "uq_plan_item_position" ...
# Key (section_id, parent_id, ord)=(…, null, 1) is duplicated`. На чистой базе
# запрос трогает ноль строк.
#
# Перенумеровывается **уровень целиком**, а не одна лишняя строка: `ord` плотный
# и считается с нуля (`app/crud/plan.py:207` нумерует братьев через `enumerate`),
# поэтому после починки уровень выглядит ровно так, как его записал бы сам сервис.
# Трогаются только уровни, где дубль есть: уровень с дырами (0, 5, 10) — законная
# история, и уплотнять его миграции незачем.
#
# Порядок внутри уровня — `ord`, затем `starts_at`, затем `created_at`, затем `id`:
#
# * `ord` первым, поэтому пункты, чьи номера и так различались, остаются на своих
#   местах друг относительно друга. Двигаются только те, кто делил номер;
# * `starts_at` (пустые — в конец) решает спор о том, что человек увидит выше.
#   Номер потерян, а окно — нет: план читается по часам дня, и пункт на 08:00
#   должен стоять над пунктом на 09:00, даже если оба записаны под номером 1.
#   Пункт без окна — `bullet`, свободный вечер — уходит под пункты с окном;
# * `created_at` — порядок, в котором строки легли в базу, то есть порядок строк
#   в исходном документе дня: импорт пишет план сверху вниз;
# * `id` последним и только ради определённости. Это `uuid4`, осмысленного
#   порядка в нём нет, но у `created_at` стоит `now()` — время транзакции, одно
#   на все пункты плана, записанного одним заходом. Без `id` такой уровень
#   получал бы на повторном прогоне разный порядок.
#
# Почему это безопасно: ни одна строка не удаляется и не добавляется, меняется
# только `ord`. Ссылки на пункт идут по `id` — `parent_id`, `carried_from_item_id`,
# отметки `plan_mark`; внешним ключом `ord` не является нигде, а уникальность
# `(section_id, code)` от него не зависит. Ниже по истории `ord` попадает в
# `plan_item_change` (`e5b7d9f1a3c6`) — это журнал правок, снимок прошлого, и он
# должен остаться таким, каким был записан.
RENUMBER_DUPLICATE_POSITIONS = """
    WITH crowded AS (
        SELECT section_id, parent_id
        FROM plan_item
        GROUP BY section_id, parent_id, ord
        HAVING count(*) > 1
    ),
    levels AS (
        SELECT DISTINCT section_id, parent_id FROM crowded
    ),
    renumbered AS (
        SELECT i.id,
               ROW_NUMBER() OVER (
                   PARTITION BY i.section_id, i.parent_id
                   ORDER BY i.ord, i.starts_at NULLS LAST, i.created_at, i.id
               ) - 1 AS new_ord
        FROM plan_item i
        JOIN levels l
          ON l.section_id = i.section_id
         AND l.parent_id IS NOT DISTINCT FROM i.parent_id
    )
    UPDATE plan_item p
    SET ord = r.new_ord
    FROM renumbered r
    WHERE p.id = r.id
      AND p.ord <> r.new_ord
"""


def upgrade() -> None:
    op.add_column(
        "plan_item",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "plan_item",
        sa.Column(
            "edited_by",
            sa.String(length=8),
            server_default="ai",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_plan_item_edited_by",
        "plan_item",
        "edited_by IN ('" + "', '".join(EDITORS) + "')",
    )
    op.execute(RENUMBER_DUPLICATE_POSITIONS)
    op.execute(POSITION_UNIQUE)


def downgrade() -> None:
    # Позиции назад не разъезжаются. Прежнее состояние — два пункта под одним
    # номером, то есть отсутствие порядка, а не другой порядок: восстанавливать
    # там нечего, и повтор upgrade даст тот же результат, что и первый прогон.
    op.drop_constraint("uq_plan_item_position", "plan_item", type_="unique")
    op.drop_constraint("ck_plan_item_edited_by", "plan_item", type_="check")
    op.drop_column("plan_item", "edited_by")
    op.drop_column("plan_item", "updated_at")
