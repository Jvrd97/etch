---
id: ADR-0014
title: "День CTO в Postgres: personal-os поглощается habit_tracker_ai"
status: in-review
phase: PHASE-03
owner: Даниил Быстров
authors: [Даниил Быстров]
created: 2026-08-30
decided: 2026-08-30
approved_by:
approved_at:
supersedes:
superseded_by:
services: [backend, frontend, macos-agent]
related: [ADR-0002, ADR-0003, ADR-0005, ADR-0007]
tracker_ref:
---

# ADR-0014: День CTO в Postgres — personal-os поглощается habit_tracker_ai

## Status

Принято (2026-08-30) — in-review. Реализация разбита на десять вертикальных срезов (см. `## Related`).

## Context

Есть две системы, которые описывают один и тот же день одного человека.

**personal-os** (`~/Documents/MyProj/personal-os`) — файловая. День живёт в `plans/YYYY/MM/YYYY-MM-DD.md`: шапка с «ради чего», разделы, задачи `W1..W4` с окнами `Окно :: 09:30-11:00`, критериями «Сделано ::» и «Минимум ::», таблица жёстких точек, свободный вечерний блок. `tools/plan_html.py` рисует из этого HTML, `tools/plan_server.py` (673 строки, слушает `127.0.0.1:8787`, аутентификации нет) отдаёт страницу и принимает отметки, `tools/life.py` собирает таймлайн жизни, `tools/install_plan_app.sh` вешает иконку в Dock. Итог дня — `summaries/`, неделя — `weeks/`, тренировки — `training/state.md`, цели и милстоны M1-M10 — `goal.md`, канон правил — `config.md`.

**habit_tracker_ai** — сервисная: FastAPI + SQLAlchemy 2.0 async + PostgreSQL 16 + Next.js, десять таблиц, EAV-ядро `categories → fields → entries → entry_values`, журнал, health-контур с почасовыми корзинами, LLM-слой. Развёрнута на VPS в tailnet, наружу не публикуется (ADR-0003).

Три факта делают слияние неизбежным, а не желательным.

**Источник истины в personal-os тройной и противоречивый.** Текст плана — `.md`; отметки — производный `.html`, который в `.gitignore`, то есть истории отметок в git не существует вообще; чекбоксы `- [x]` — снова `.md`, и их читают `life.py` и telegram-бот, а `plan_html.py` не читает. Ключ отметки — порядковый номер в DOM (`i7`, `t3`, `w1`), поэтому правка одной строки `.md` молча сдвигает соответствие «отметка ↔ пункт». Физически на диске осталось три файла с отметками (28, 29, 31 августа) — вся история отметок системы.

**Критерий «день выигран» существует в трёх несовместимых версиях.** `config.md` — «все 4 задачи и работа ≤ 8 ч со стопом в 16:00»; `.claude/skills/day-close/SKILL.md` — «якоря и ≥ 80% задач»; `templates/summary.md` и `docs/PRD.md` — «≤ 10 ч». Планка задач тоже расходится: 4 против 5. Машина вытаскивает вердикт регуляркой из прозы (`**Нет.**` под заголовком `## День выигран?`) в двух местах независимо — `life.py` и `plan_server.py`.

**Правила уже менялись и будут меняться.** «≤ 10 ч» стало «≤ 8 ч» 2026-08-17 с объяснением «десять часов оказались не потолком, а нормой, за которой шли два дня без спорта». Планка «сколько задач» менялась тогда же. Метрика учёбы «3 раза в неделю по 15 минут» простояла 0/3 шесть недель и была заменена на режим. Любая схема, где эти числа — константы в коде, перепишет прошлое при следующей правке канона.

Плюс два фоновых ограничения. Система однопользовательская по построению: ни таблицы `users`, ни колонки `user_id`, вся защита — статический `X-API-Key`, и пустой ключ отключает её совсем. Часового пояса нет нигде, кроме health-корзин: `entry_date` трактуется как UTC-день, «сегодня» в `plan_server.py` — локальная дата машины, «код за день» — календарные 00:00-23:59, из-за чего коммит в 00:01 приписан следующему дню (зафиксировано в `feedback.md`, 2026-08-29).

Решения человека, под которые строим и которые не обсуждаются: personal-os сливается целиком, MD перестаёт быть источником истины, `plan_server.py`/`plan_html.py`/`life.py`/приложение в Dock уходят, скиллы `/day-open` и `/day-close` остаются и работают через API. Основной интерфейс — браузер на маке; отдельный маленький локальный агент macOS считает время по приложениям (только активное приложение и заголовок окна, никаких скриншотов) и держит плавающее окно. Ручной ввод первичен: любая автоматически посчитанная запись правится руками постфактум.

## Decision

**День становится набором собственных реляционных таблиц в существующей базе habit_tracker_ai, EAV-ядро не трогается, а канон дня (потолок часов, планка задач, обязательные якоря, граница суток) хранится версионированной строкой `day_rule_set`, а не константами в коде.** Вердикт «день выигран» вычисляется чистой функцией из фактов дня и того правила, которое действовало в этот день.

Ниже — десять решений, каждое с проверкой «как понять, что сделано правильно».

### Р1. День — отдельные таблицы, не EAV

Плану дня нужны упорядоченные вложенные пункты со стабильными идентификаторами, окна как интервалы времени, критерии «Сделано» и «Минимум» с собственными отметками, ссылка на квартальную цель. EAV даёт «значение полем по строке», где всё — `Text`, `(entry_id, field_id)` не уникален и поле не проверяется на принадлежность категории. Выразить в нём план дня можно, но каждый читатель начнёт угадывать структуру заново — ровно та болезнь, которую ADR-0007 лечил в чек-листах.

Модель дня — не пользовательская выдумка, ради которой EAV существует. Это канон `config.md`: он меняется раз в месяц строкой правила, а не новой категорией, и «добавить категорию без миграции» здесь не нужно ни разу.

Точки стыковки с существующим оставляем ровно три: блокнот дня пишется в существующий `journal_entries` через `write_day_journal` (одна запись на дату, режимы append/create/replace уже разобраны); здоровье читается из `health_hour_buckets` как есть; EAV-записи и трекерные категории попадают в ответ дня как отдельная секция, без слияния схем.

**Проверка:** `GET /api/v1/day/{date}` отдаёт план, отметки, итог, здоровье и трекерные записи одним ответом, и ни один новый запрос не читает `entry_values`.

### Р2. Канон дня — строка `day_rule_set`, действующая на интервале дат

Потолок рабочего времени, жёсткий потолок-исключение, время стопа, максимум рабочих задач, список обязательных якорей, доля закрытых задач для победы, дисквалифицирует ли переработка, час границы суток, часовой пояс, рабочие дни, no-code дни — поля одной строки с `daterange(valid_from, valid_to)` и GiST-исключением на пересечение. Каждый `day` ссылается на правило, действовавшее в этот день; каждый `day_summary` хранит `rule_set_id`, по которому вердикт был вычислен.

Три конфликтующие версии критерия разрешаются так: действующая строка берёт цифры `config.md` (8 ч, стоп 16:00, 4 задачи, все четыре, переработка дисквалифицирует), а для импортированной истории заводится строка `legacy` с прежними числами (10 ч, 80% задач) — импортированные вердикты не пересчитываются, а переносятся как записаны.

**Проверка:** изменение потолка часов с 8 на 9 — это `INSERT` строки правила и ноль строк кода; вердикты дней до даты изменения не меняются, что доказывает тест «пересчёт всей истории идемпотентен».

### Р3. «Не перезакручивать» и «переработка = проигранный день» выражены в схеме

Оба правила перестают быть прозой в `config.md` и становятся проверяемыми:

- `plan_item.rigidity` — `hard | soft | free`. Жёсткими могут быть только края дня из `day_rule_set.required_anchors`; проверка на уровне сервиса при приёме плана.
- `CHECK (rigidity <> 'free' OR starts_at IS NULL)` — **пункт свободного блока не может иметь окна**. Свободный вечерний блок физически нечем расписать задачами.
- `CHECK (kind <> 'task' OR (starts_at IS NOT NULL AND ends_at IS NOT NULL AND done_criterion IS NOT NULL))` — у рабочей задачи обязаны быть окно и критерий «сделано» (канон от 2026-08-28).
- Планка задач: сервис отклоняет план с числом пунктов `kind='task'` больше `day_rule_set.max_work_tasks` (422). Не триггером — план приезжает одним документом и валидируется целиком, а построчный триггер сорвал бы импорт исторических дней, которые планку нарушали.
- Переработка: `day_summary.work_minutes > rule.work_hours_cap_min AND rule.overtime_disqualifies` → `verdict='lost'`, `verdict_reason='overtime'`, независимо от доли закрытых задач.

**Проверка:** три негативных теста — план с пятой задачей отклонён; пункт свободного блока с окном отклонён; день с 4/4 задачами и 9 часами работы получает `lost` с причиной `overtime`.

### Р4. Отметка привязана к uuid пункта, а не к позиции; «пусто» различает четыре состояния

`plan_item.id` — uuid, выданный при создании пункта. `plan_mark` — одна строка на пункт с `state ∈ {done, failed, skipped}`, заметкой «как прошло», `updated_at` и `source`. Отсутствие строки = `pending`. Отдельно `day.opened_at` фиксирует, заходил ли человек на страницу дня вообще.

Так различаются четыре разных «пусто», которые сегодня неразличимы: **не дошёл** (`pending`, страница открывалась), **не открывал** (`pending`, `opened_at IS NULL`), **не сделал** (`failed`), **стало неактуально** (`skipped`). 29 августа — день с нулём отметок — после импорта читается как «не открывал», а не как «ничего не сделал».

Заплатки `plan_server.py` (409 «пустое поверх непустого», подмешивание `localStorage`, перечитывание по `visibilitychange`) не воспроизводятся: их место занимает транзакция плюс `updated_at` на каждой отметке. `plan_mark_event` — append-only лог смен состояния, потому что git больше не версионирует отметки.

**Проверка:** правка текста пункта не меняет ни одной отметки; после импорта 29 августа `opened_at IS NULL` и ни одной строки `plan_mark`.

### Р5. Поля пункта: шесть закрытых, остальное — `jsonb`

В живых планах встречается больше пятнадцати подписей `Подпись :: значение`. Закрываем в колонки те шесть, по которым нужны запросы и проверки: `Окно` → `starts_at`/`ends_at`/`window_comment`, `Сделано` → `done_criterion`, `Минимум` → отдельный дочерний пункт `kind='minimum'` со своей отметкой, `ClickUp` → `external_ref jsonb`, `Почему` → `why_md`, `Ход` → `plan_md`. Всё остальное (`Факт`, `Формат`, `Вход`, `Материал`, `Репозиторий`, `Что писать`) — в `extra jsonb`, без потери и без схемы.

Минимум становится собственным пунктом с собственной галкой намеренно: 29 августа доказало, что объявленный внутри задачи минимум без отдельной отметки не работает.

**Проверка:** импорт живых планов 28-31 августа не теряет ни одной подписи; у каждой тренировки с объявленным минимумом есть отдельный отмечаемый пункт.

### Р6. Сутки — локальный календарный день с настраиваемой границей

`day_rule_set.timezone` (по умолчанию `Europe/Berlin`) и `day_rule_set.day_start_hour` (по умолчанию 4). Все `date`-колонки — локальные даты, все моменты — `timestamptz`. Коммит, интервал работы и семпл здоровья приписываются дню по правилу «от `day_start_hour` до `day_start_hour` следующих суток», что чинит известный дефект «коммит в 00:01 уехал в новый день». Окно через полночь (`ends_at <= starts_at` в исходном тексте) разворачивается в `+24 ч` при разборе, как в `parse_window`.

**Проверка:** тест «коммит 2026-08-29 00:01 приписан дню 2026-08-28»; тест «окно 23:30-00:30 даёт 60 минут, а не отрицательную длительность».

### Р7. Время работы — таблица `work_interval`, ручной ввод первичен

Ручная запись и автоматически посчитанная лежат в одной таблице и различаются полем `source ∈ {manual, agent, corrected}`. Правка агентского интервала не затирает исходное предложение: `auto_started_at`/`auto_ended_at` сохраняются рядом, `edited_at` помечает вмешательство. Режим «работаю / не работаю» — поле `mode` на интервале; он приезжает от расписания или от ручного переключателя, автоопределение по активности не делается.

Граница приватности проходит здесь: **в день попадают только интервал, режим и `app_bundle_id`; заголовки окон в модель дня не переносятся вообще.** Агент может использовать их локально, чтобы разложить время по приложениям, но текст заголовка — это содержимое переписки, документа и медицинской карточки одновременно, и в базе дня ему места нет. Если заголовки понадобятся, они заводят собственную таблицу в ADR агента и не входят в состав ответа `GET /day/{date}` по умолчанию.

`work_minutes IS NULL` означает «не измерено» и не равно нулю: проверка на переработку в этот день пропускается, а `missing_data` получает отметку. Это то же правило, по которому `fold_daily` возвращает `None` при нулевом счётчике — отсутствие измерения не превращается в измеренный ноль.

**Проверка:** интервал, посчитанный агентом и исправленный руками, отдаёт и исправленное, и исходное значение; день без единого интервала не получает `lost` с причиной `overtime`.

### Р8. Вердикт — чистая функция, а не проза и не регулярка

`evaluate_day(rule_set, facts) -> Verdict(verdict, reason, anchors_done/total, tasks_done/total, work_minutes, missing_data)` — без БД и без HTTP, по образцу `app/health/aggregate.py`. `day_summary.verdict` хранит результат, `verdict_reason` — машинную расшифровку, какое именно условие не выполнено. Ручное переопределение возможно (`verdict_override` + обязательная записка), потому что человек имеет право сказать «день был выигран, просто я не отметил», но это видимое действие, а не молчаливая правка.

Проза итога никуда не девается: `day_summary.body_md` хранит разделы «Что случилось вместо плана», «Что мешало», честные оговорки — половина ценности данных именно там. По всем текстовым колонкам — генерируемые `tsvector` с русской конфигурацией и GIN-индексы.

**Проверка:** ни один код, кроме импортёра, не разбирает вердикт регуляркой; таблица истины `evaluate_day` покрыта тестами по всем причинам (`tasks`, `anchors`, `overtime`, `not_closed`).

### Р9. Что заменяет `plan_server.py`, `life.html` и приложение в Dock

| Уходит | Приходит |
|---|---|
| `plan_server.py` `/` и `/YYYY-MM-DD` | `GET /api/v1/day/{date}` + страница `/day/[date]` в Next.js |
| `plan_server.py` `/save` с позиционными ключами | `PUT /api/v1/day/{date}/marks/{item_id}` |
| `plan_server.py` `/api/days` и `side.js` | `GET /api/v1/days?from&to` + существующая боковая навигация |
| `life.py` → `life.html` | страница `/life` поверх `GET /api/v1/days` |
| `plan_html.py` | серверный рендер плана из строк; markdown остаётся форматом импорта и экспорта |
| кнопка «Сделать план на завтра» + `claude -p` в фоне | `POST /api/v1/day/{date}/handoff` + таблица `day_job` |
| `~/Applications/План дня.app` | не воспроизводится: браузер — основной интерфейс, быстрые отметки и таймер живут в плавающем окне локального агента |
| `tools/tgbot/` (правит чекбоксы в `.md`) | выводится из эксплуатации явным пунктом среза 10; Telegram-вход — предмет отдельного ADR |

`day_job` — таблица со `state ∈ {queued, running, done, failed, stale}`, `heartbeat_at` и частичным уникальным индексом «одна активная задача на день и действие». Запускается фоновой `asyncio`-задачей внутри воркера FastAPI. Ни Celery, ни APScheduler: одна задача в сутки на одного пользователя не оправдывает второй контейнер. Принятый риск — перезапуск воркера теряет задачу в полёте; лечится сметанием `running` без свежего `heartbeat_at` в `stale` при старте приложения.

**Проверка:** `plan_server.py` не запускается ни разу за неделю, а день закрывается и открывается с той же страницы; `docs/plan-app.md` заменён разделом в `docs/` habit_tracker_ai.

### Р10. `/day-open` и `/day-close` — через API, план приезжает одним документом

Скиллы перестают писать файлы. `/day-open` читает `GET /api/v1/day/{date}/context` — один составной ответ: действующее правило, цель квартала и милстоны, отметки и итог вчерашнего дня, состояние тренировок и открытые жалобы, очередь учёбы, незакрытые переносы. Затем отправляет `POST /api/v1/day/{date}/plan` — весь план одним JSON-документом, который валидируется целиком: планка задач, окно у каждой задачи, отсутствие окон в свободном блоке, привязка задачи к пункту квартала.

Правило `goal.md` «задача, не связанная ни с одним пунктом квартала, — чужая срочность, и это говорится вслух» становится валидацией: `CHECK (kind <> 'task' OR quarter_goal_id IS NOT NULL OR unlinked_reason IS NOT NULL)`. Молча вписать несвязанную задачу нельзя — придётся написать, почему она здесь.

Правило трёх переносов тоже перестаёт быть дисциплиной: `carryover.times_moved >= 3` заставляет API требовать явное `decision ∈ {moves, closed_stale, decided_not_to_do}`, иначе пункт в новый план не принимается.

**Проверка:** план, где у задачи нет ни цели квартала, ни причины, получает 422 с указанием кода задачи; пункт, переезжающий четвёртый раз без решения, отклоняется.

### Модель данных

Новые таблицы (SQLAlchemy 2.0 `Mapped[]`/`mapped_column()`, Alembic-ревизия на каждый срез, все reversible).

**Канон и день**

```sql
day_rule_set(
  id serial PK, valid_from date NOT NULL, valid_to date NULL,
  timezone text NOT NULL DEFAULT 'Europe/Berlin',
  day_start_hour smallint NOT NULL DEFAULT 4,
  work_cap_min int NOT NULL DEFAULT 480, work_hard_cap_min int NOT NULL DEFAULT 540,
  work_stop_at time NOT NULL DEFAULT '16:00',
  max_work_tasks smallint NOT NULL DEFAULT 4,
  tasks_required_ratio numeric(3,2) NOT NULL DEFAULT 1.00,
  overtime_disqualifies boolean NOT NULL DEFAULT true,
  workdays smallint[] NOT NULL, nocode_days smallint[] NOT NULL,
  required_anchors text[] NOT NULL, note_md text NOT NULL DEFAULT '',
  EXCLUDE USING gist (daterange(valid_from, valid_to, '[)') WITH &&))

day(
  date date PK, rule_set_id int FK NOT NULL,
  kind text NOT NULL CHECK (kind IN ('work','off')),
  is_nocode boolean NOT NULL,
  opened_at timestamptz NULL, last_touched_at timestamptz NULL,
  created_at, updated_at timestamptz NOT NULL)
```

`kind` и `is_nocode` материализуются при создании дня, а не выводятся на чтении: расписание недели уже менялось 2026-08-17, и прошлый вторник обязан остаться тем, чем был.

**План**

```sql
day_plan(id uuid PK, day_date date FK day UNIQUE, title text, title_marker text,
  lede text, purpose_md text, quarter_goal_id int FK NULL,
  counters jsonb NOT NULL DEFAULT '[]', condition_tomorrow text,
  status text CHECK (status IN ('draft','active','closed')),
  source text CHECK (source IN ('day-open','import','manual')),
  raw_md text, created_at, updated_at)

plan_section(id uuid PK, plan_id uuid FK ON DELETE CASCADE, ord smallint,
  title text, kind text NOT NULL,          -- anchors|training|hard_points|work|study|evening|personal|queue|free|other
  UNIQUE(plan_id, ord))

plan_item(
  id uuid PK, section_id uuid FK ON DELETE CASCADE,
  parent_id uuid FK plan_item NULL, ord smallint NOT NULL,
  kind text NOT NULL,        -- bullet|step|table_row|task|anchor|hard_point|minimum
  rigidity text NOT NULL DEFAULT 'soft' CHECK (rigidity IN ('hard','soft','free')),
  text_md text NOT NULL, text_plain text NOT NULL,
  starts_at timestamptz NULL, ends_at timestamptz NULL, window_comment text NULL,
  code text NULL, done_criterion text NULL, why_md text NULL, plan_md text NULL,
  external_ref jsonb NULL, extra jsonb NOT NULL DEFAULT '{}',
  quarter_goal_id int FK NULL, unlinked_reason text NULL,
  carried_from_item_id uuid FK plan_item NULL, carry_count smallint NOT NULL DEFAULT 0,
  legacy_key text NULL,
  window tstzrange GENERATED ALWAYS AS (tstzrange(starts_at, ends_at)) STORED,
  search tsvector GENERATED ALWAYS AS (to_tsvector('russian', text_plain)) STORED,
  CHECK (kind <> 'task' OR (starts_at IS NOT NULL AND ends_at IS NOT NULL
                            AND done_criterion IS NOT NULL)),
  CHECK (rigidity <> 'free' OR starts_at IS NULL),
  CHECK (kind <> 'task' OR quarter_goal_id IS NOT NULL OR unlinked_reason IS NOT NULL),
  CHECK (starts_at IS NULL OR ends_at > starts_at))
```

Индексы: `(section_id, ord)`, GiST на `window` (наложения — самосоединение по `&&`, а не пересчёт на каждый рендер), GIN на `search`, `(carried_from_item_id)`, частичный `UNIQUE(section_id, code) WHERE code IS NOT NULL`.

**Отметки и блокнот**

```sql
plan_mark(id uuid PK, item_id uuid FK plan_item UNIQUE ON DELETE CASCADE,
  state text NOT NULL CHECK (state IN ('done','failed','skipped')),
  note text, marked_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
  source text NOT NULL CHECK (source IN ('web','agent','import','llm')))

plan_mark_event(id bigserial PK, item_id uuid FK, state text, note text,
  changed_at timestamptz NOT NULL, source text NOT NULL)
```

Блокнот дня — существующий `journal_entries` через `write_day_journal`; своей таблицы не заводит.

**Якоря, время работы, тренировка**

```sql
anchor_kind(code text PK, title text, ord smallint, counts_for_verdict boolean NOT NULL)
day_anchor(id uuid PK, day_date date FK day, kind text FK anchor_kind,
  item_id uuid FK plan_item NULL, state text NULL, note text, UNIQUE(day_date, kind))

work_interval(id uuid PK, day_date date FK day, started_at timestamptz NOT NULL,
  ended_at timestamptz NULL, source text CHECK (source IN ('manual','agent','corrected')),
  mode text NOT NULL CHECK (mode IN ('work','off')),
  auto_started_at timestamptz NULL, auto_ended_at timestamptz NULL,
  app_bundle_id text NULL, note text, edited_at timestamptz NULL,
  CHECK (ended_at IS NULL OR ended_at > started_at))
  -- индекс GiST на tstzrange(started_at, ended_at)

training_day(day_date date PK FK day, patterns text[] NOT NULL DEFAULT '{}',
  planned_md text, done_md text, skipped boolean NOT NULL DEFAULT false,
  minimum_md text, minimum_item_id uuid FK plan_item NULL,
  outdoor_done boolean NULL, sets jsonb NOT NULL DEFAULT '{}')

training_state(id smallint PK CHECK (id = 1), last_heavy_pull date, last_heavy_push date,
  last_legs date, last_run date, last_outdoor date, last_cardio date,
  near_failure_days date[], week_sets jsonb, progression_stage jsonb,
  skipped_days int, recomputed_at timestamptz NOT NULL)

body_complaint(id uuid PK, opened_on date NOT NULL, area text NOT NULL, context text,
  severity text, status text CHECK (status IN ('open','closed')),
  closed_on date NULL, closed_reason text NULL)

personal_record(id uuid PK, exercise text, variant text, sets text,
  best_plain int NULL, achieved_on date NOT NULL, target text)
```

`training_state` — производный снимок с чистой функцией пересчёта из `training_day` и `body_complaint`, а не источник истины. Динамические YAML-ключи `planned_<date>`/`done_<date>`/`skipped_<date>` разворачиваются в строки `training_day` — именно свёрнутая во frontmatter таблица и была источником боли.

**Итог, неделя, цели, переносы, служебное**

```sql
day_summary(day_date date PK FK day, rule_set_id int FK NOT NULL,
  verdict text NULL CHECK (verdict IN ('won','lost')), verdict_reason text NOT NULL DEFAULT '',
  verdict_override boolean NOT NULL DEFAULT false, verdict_override_note text NULL,
  anchors_done smallint, anchors_total smallint, tasks_done smallint, tasks_total smallint,
  work_minutes int NULL, streak_after int NULL, wrote_from_scratch smallint NULL,
  education_debt smallint NULL, reviewed_today smallint NULL,
  body_md text NOT NULL DEFAULT '', missing_data text[] NOT NULL DEFAULT '{}',
  search tsvector GENERATED,
  CHECK (NOT verdict_override OR verdict_override_note IS NOT NULL))

week(iso_code text PK, starts_on date, ends_on date, won_days smallint, total_days smallint,
  streak_end int, retro_md text, blockers_md text, mgmt_retro_md text,
  weekly_number_md text, computed_at timestamptz, search tsvector GENERATED)
week_review_item(id uuid PK, week_iso text FK, ord smallint, text_md text, done boolean)

goal_level(level smallint PK CHECK (level BETWEEN 0 AND 5), title text, body_md text,
  open_questions text[] NOT NULL DEFAULT '{}')
milestone(code text PK, title text, done_criterion text, when_text text,
  status text CHECK (status IN ('open','in-progress','done','dropped')),
  done_on date NULL, ord smallint)
milestone_dep(milestone_code text FK, depends_on_code text FK, PRIMARY KEY (…))
quarter_goal(id serial PK, quarter text, ord smallint CHECK (ord BETWEEN 1 AND 5),
  text_md text, milestone_code text FK NULL, status text, UNIQUE(quarter, ord))

carryover(id uuid PK, item_id uuid FK plan_item, origin_item_id uuid FK plan_item,
  from_date date, to_date date, times_moved smallint NOT NULL DEFAULT 1,
  decision text NULL CHECK (decision IN ('moves','closed_stale','decided_not_to_do')))

day_job(id uuid PK, day_date date, action text, state text, started_at timestamptz,
  finished_at timestamptz, heartbeat_at timestamptz, log_path text,
  result jsonb, error text)
  -- UNIQUE(day_date, action) WHERE state IN ('queued','running')

friction_entry(id uuid PK, noted_on date, text_md text, source text)
import_source(id uuid PK, kind text, path text, sha256 text, imported_at timestamptz, raw text)
```

`quarter_goal.ord BETWEEN 1 AND 5` делает правило «ровно пять задач на квартал» фактом схемы. `milestone_dep` разворачивает колонку «Открывается чем» в граф — иначе M4→M2 и M10→M9+M8 остаются текстом.

### Миграция истории

Не Alembic-миграция, а идемпотентный CLI `uv run python -m app.imports.personal_os --root <path>`:

1. `plans/**/*.md` — портированный парсер `plan_html.py` (`split_front`, `WINDOW_RE`, ветка `' :: '`, `POINT_RE`) даёт секции, пункты, задачи, окна, поля. Естественный ключ — дата, повторный запуск переписывает день целиком.
2. Три сохранившихся `plans/**/*.html` — блок `<script id="plan-state">` читается, ключи `i<n>`/`t<n>/w<n>/u<n>` сопоставляются с пунктами **в том же порядке обхода, что и в `initPlan()`**, и записываются в `plan_item.legacy_key`. Отметка, для которой пункт не нашёлся, не теряется — уходит в `import_source.raw` с явным предупреждением в отчёте импорта.
3. `summaries/**/*.md` → `day_summary` с `rule_set_id = legacy`, вердикт переносится как записан (регулярка `VERDICT_VALUE` живёт только здесь), проза целиком в `body_md`.
4. `weeks/`, `goal.md` (уровни, M1-M10, квартал), `training/state.md` (frontmatter + датированные заметки), `feedback.md` — по своим таблицам.
5. Внутренние относительные ссылки (`../../../weeks/2026/2026-W35.md`) переписываются в ссылки приложения; неразобранные остаются текстом и попадают в отчёт.
6. Каждый файл кладётся в `import_source` целиком с `sha256`. Ничто не удаляется из personal-os: репозиторий замораживается в архив после приёмки.

**Проверка:** повторный запуск импорта даёт нулевую разницу; отчёт печатает число дней, пунктов, перенесённых отметок и список того, что не разобралось; дни без summary (15-16 и 21-27 августа) существуют как `day` без `day_summary`, а не как пробел.

### Граница второго пользователя

Сегодня `user_id` нет нигде и заводить его не будем — это цена, которую платит однопользовательская система за отсутствие лишнего JOIN на каждом запросе. Но граница проведена явно: **корневых таблиц шесть — `day`, `day_rule_set`, `training_state`, `goal_level`, `milestone`, `quarter_goal`.** Всё остальное висит на них через FK и о владельце не знает. Второй пользователь — одна миграция: `owner_id` в эти шесть таблиц, переопределение шести уникальных ключей (`day.date`, `week.iso_code`, `milestone.code`, `quarter_goal(quarter, ord)`, `training_state.id`, диапазон `day_rule_set`) на составные с `owner_id`, плюс скоуп в шести CRUD-функциях. Естественные ключи выбраны так, чтобы это была механическая правка, а не редизайн.

Чего мы при этом не делаем: не добавляем `owner_id` «на будущее» пустой колонкой и не заводим таблицу `users` без входа. Пустой ключ владельца хуже отсутствующего — он создаёт иллюзию изоляции, которой нет.

### Медицинские и личные данные

**Хранится:** текст плана и итога дня со всей прозой, отметки и заметки «как прошло», блокнот дня, интервалы работы и режим, `app_bundle_id`, объём и паттерны тренировки, жалобы на тело (`body_complaint.area` — «левое плечо», контекст и тяжесть), личные рекорды, метрики Apple Health (сон, шаги, HRV, пульс покоя) в почасовых корзинах, цели и милстоны, включая финансовые формулировки вроде доли 15%.

**Не хранится:** скриншоты — никогда и ни в каком виде (отвергнуто человеком явно); заголовки окон в модели дня; диагнозы, назначения, препараты, результаты анализов — жалоба «кольнуло плечо» это симптом для гейта тренировки, а не медицинская запись; содержимое чужой переписки; пароли и токены.

**Режим обращения:** ничего из перечисленного не уходит в логи (`echo=False` на движке, правило «никаких PII в логах» распространено на тексты пользователя). Ничего не уходит в векторное хранилище — по CLAUDE.md §4 пользовательские данные живут только в PostgreSQL/Redis, и жалобы на тело здесь не исключение. В контекст LLM отдаётся только то, что нужно конкретному вызову: `/train` видит жалобы и объём, разбор дня — план и отметки; целиком день модели не скармливается. Наружу база не смотрит: VPS только в tailnet (ADR-0003), `X-API-Key` обязателен.

**Открытый риск:** пустой `API_KEY` до сих пор отключает аутентификацию целиком, а CORS стоит `allow_origins=["*"]`. Для ручек дня это надо ужесточить в том же срезе, где они появляются, иначе туда переезжают жалобы на тело и цели по деньгам под защитой одного лишь tailnet.

## Options considered

### Вариант A: день ложится в существующий EAV (категория «День», поля-галки)

- **Описание**: каждый пункт плана — boolean-поле checklist-категории, отметка — `entry_value`, прочее — `notes`.
- **Плюсы**: ноль новых таблиц, готовые Today/Table/streak/idempotency, готовый UI.
- **Минусы**: нет порядка и вложенности, нет окон как интервалов, нет стабильного id пункта (поле создаётся под каждый пункт каждого дня — тысячи полей в год), нет места для прозы, `entry_values.value` — Text для всего.
- **Отвергнут потому, что** план дня меняется каждый день, а `fields` — определение категории, а не строка данных: за год получилось бы порядка полутора тысяч полей в одной категории, и `PATCH /categories` с полным desired-state удалял бы историю при каждой правке.

### Вариант B: свои таблицы дня в той же базе (выбран)

- **Описание**: раздел «Модель данных» выше; EAV не трогается, стык через `journal_entries` и составной ответ дня.
- **Плюсы**: структура выражает канон, ограничения проверяются базой, окна и наложения считаются запросом, проза индексируется полнотекстом, отметка переживает правку текста.
- **Минусы**: около двадцати новых таблиц и десять миграций; два способа хранить «факт дня» в одной базе (трекерная запись и пункт плана) — читателю придётся объяснять разницу.
- **Выбран потому, что** это единственный вариант, в котором правила `config.md` становятся проверяемыми, а не комментарием; цена — таблицы, которые всё равно пришлось бы завести внутри EAV в виде соглашений.

### Вариант C: MD остаётся источником истины, Postgres — индекс для чтения

- **Описание**: файлы живут как есть, фоновый импортёр держит зеркало в базе для поиска и графиков.
- **Плюсы**: ничего не ломается, git продолжает версионировать, откат бесплатный.
- **Минусы**: запись остаётся файловой — значит остаются позиционные ключи, отсутствие транзакции, три источника истины и `plan_server.py`; телефон и агент писать не могут.
- **Отвергнут потому, что** человек решил обратное, и по делу: половина сегодняшних дефектов (потеря отметок, конфликт «пустое поверх непустого», разъезжающиеся вердикты) — прямое следствие того, что запись идёт в файл без транзакции.

### Вариант D: правила дня — константы в коде

- **Описание**: `WORK_CAP_MIN = 480`, `MAX_TASKS = 4` в `app/day/rules.py`.
- **Плюсы**: проще на одну таблицу, правило видно в тестах.
- **Минусы**: смена правила переписывает вердикты всей истории; невозможно объяснить, почему 14 августа считалось иначе.
- **Отвергнут потому, что** канон уже менялся дважды за месяц, и оба раза — с явным объяснением, что старое правило было неверным для того периода, а не всегда.

## Consequences

### What becomes easier

- Один вопрос — один запрос: «сколько дней подряд выигранных», «в какие дни задача переезжала трижды», «где пересекались окна» перестают быть перечитыванием файлов.
- Отметка с телефона и из плавающего окна агента становится обычным `PUT` с транзакцией; офлайн-очередь iOS (`OutboxQueue`) работает по тем же `Idempotency-Key`, что и записи трекера.
- Правило дня меняется вставкой строки, и прошлое остаётся тем, чем было.
- «Не перезакручивать», планка четырёх задач и связь задачи с целью квартала перестают зависеть от того, вспомнил ли агент правило: их отклоняет API.
- Проза дня становится искомой: «когда я последний раз писал, что мешал монитор» — один запрос по GIN-индексу.

### What becomes harder

- Отредактировать план в текстовом редакторе больше нельзя. Единственный путь правки — интерфейс или API; на маке без сети это означает, что план временно недоступен на запись (браузер офлайна не имеет, service worker'а в вебе нет).
- Схема дня перестаёт быть свободной: новая подпись `Подпись :: значение` попадает в `extra jsonb` и по ней нельзя фильтровать без миграции. Свобода формата, которой пользовался автор планов, платит за проверяемость.
- Число таблиц в базе утраивается, и разница между «трекерная запись» и «пункт плана» требует объяснения в `docs/`, иначе следующая фича напишет данные не туда.
- Git перестаёт быть журналом изменений дня; его заменяют `plan_mark_event` и `import_source`, и бэкап базы становится обязательным, а не желательным (`deploy/backup.sh` попадает в критический путь).
- Скиллы `/day-open` и `/day-close` начинают зависеть от доступности VPS: нет tailnet — нет плана.

### What new risks did we accept

- **Фоновая задача внутри воркера.** `day_job` исполняется `asyncio`-задачей в процессе FastAPI; перезапуск воркера теряет её в полёте. Смягчение — `heartbeat_at` и сметание в `stale` на старте; сигнал к пересмотру — вторая потеря задачи за месяц.
- **Единственная копия дня.** Пока `.md` были в git, потеря базы стоила отметок. Теперь она стоит всего; ежедневный бэкап становится условием эксплуатации.
- **Импорт по позиционным ключам ненадёжен по построению.** Три файла с отметками сопоставляются с пунктами по порядку обхода DOM; если порядок сместился, отметка сядет не на тот пункт. Смягчение — предупреждения в отчёте и сохранение исходника; цена ошибки мала (три дня).
- **Ужесточение аутентификации откладывается в срез, а не в отдельный тикет.** До него ручки дня защищены только tailnet и `X-API-Key`, который отключается пустым значением.
- **Расхождение с CLAUDE.md §4 про LangChain** остаётся: LLM-слой по-прежнему на голом SDK/CLI (ADR-0006 постановил обратное). Этот ADR его не чинит и не углубляет — просто фиксирует, что новые вызовы идут через тот же `app/llm/`.

### What we're explicitly NOT solving (yet)

- Локальный агент macOS: сбор активного приложения, плавающее окно, переключатель режима, расписание — отдельный ADR. Здесь определён только контракт `work_interval`, в который агент пишет.
- Telegram как вход и Gmail-разбор писем — отдельные ADR; в модели дня для них зарезервировано только `plan_item.external_ref`.
- Офлайн в вебе (service worker) и установка страницы дня на телефон.
- Составные индексы на существующих `entries` и `fields.category_id` — известный долг EAV, к дню отношения не имеет.
- Обратная запись в ClickUp: канон read-only не меняется, `external_ref` хранит id и url, статусы не синхронизируются.
- Многопользовательность и вход по паролю.

## Reversal cost

**Medium — 1-2 недели.** Схема обратима: каждая Alembic-ревизия имеет рабочий `downgrade()`, а экспорт дня обратно в `.md` — это тот же рендер, что уже нужен для просмотра, направленный в файл. Возврат к файловому режиму стоит написать экспортёр и вернуть `plan_server.py` из архива.

Практически необратимой становится не схема, а привычка: после месяца отметок в базе `.md`-планы устареют, и откат означает потерю всего, что накопилось после точки перехода. Поэтому экспортёр «база → `plans/YYYY/MM/*.md`» пишется в том же срезе, что и импортёр, и гоняется еженедельно в архивную папку — это страховка, а не фича.

Сигнал к пересмотру: если через месяц эксплуатации доля дней, отмеченных хотя бы одним кликом, окажется ниже, чем была на файловой странице, — проблема не в хранилище, и переезд ничего не решил.

## Related

- **Related ADRs**: ADR-0002 (online-first с кэшем и очередью — та же модель для отметок дня), ADR-0003 (Tailscale + API-ключ — единственная защита ручек дня), ADR-0005 (LLM без native tool use — план дня приезжает как данные, не как вызовы инструментов), ADR-0007 (одна запись на дату — правило, по которому блокнот дня садится в `journal_entries`).
- **Code locations**: новые `app/models/day*.py`, `app/crud/day*.py`, `app/api/day.py`, `app/day/rules.py` (чистая `evaluate_day`), `app/imports/personal_os.py`; страницы `app/day/[date]/page.tsx`, `app/life/page.tsx` и мобильные пары.
- **Источники канона**: `personal-os/config.md` (день выигран, карта дня, планка, часы), `personal-os/goal.md` (уровни 0-5, M1-M10, квартал), `personal-os/training/state.md`, `personal-os/feedback.md`.
- **Выводится из эксплуатации**: `personal-os/tools/plan_server.py`, `plan_html.py`, `life.py`, `install_plan_app.sh`, `tools/tgbot/`.

## Notes

Заголовок `## День выигран?` с прозой `**Нет.**` и честной оговоркой «цифра 0/4 измеряет не работу, а её видимость» — лучший аргумент за то, чтобы вердикт был полем, а оговорка осталась прозой рядом. Схема, которая сохраняет только число, потеряет ровно ту часть, ради которой день закрывают.
