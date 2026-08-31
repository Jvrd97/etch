# Session Review Log

## 2026-08-31 — PHASE-03/147 модуль ограничений и скелет плана

Черновик плана проверяется **до** записи, восемью чистыми функциями, отвечающими кодами правил и id пунктов. Проверки `#87` остаются: база отказывает тому, что просочилось, модуль отбраковывает черновик, а его ответ уходит в ремонтный промпт `#148` — `IntegrityError` туда не положишь.

- `app/day/constraints.py` — **new**: `hard_edges_only`, `free_evening_empty`, `work_cap`, `task_cap`, `health_before_work`, `relationship_anchor_required`, `no_overlap`, `target_day_only` и `check_all(draft, rule, severity=)`. Асимметрия строгости — параметр `severity`: машине `block`, человеку `warn`. Ни одного числа в модуле: все времена, потолки и списки якорей читаются со строки `day_rule_set`.
- `app/day/skeleton.py` — **new**: `skeleton_plan(target, rule, carryovers, signals)`. Края канона, тренировочный слот, упирающийся концом в `work_start`, переносы по приоритету под двумя потолками, свободный блок пуст, якорь `relationship` — в нерабочий вечер. Что не влезло, возвращается в `overflow`, а не теряется.
- `app/models/plan_violation.py` + `alembic/.../c8f0a2b4d6e7_plan_violation.py` — **new**: `day_date`, `plan_revision_id` (под `#150`), `job_id` (под `#149`), `rule_code`, `severity`, `origin`, `detail` jsonb, индекс (`day_date`, `rule_code`). `down_revision = b7d9f1a3c5e6` — фактическая голова ветки. Downgrade реальный: проверен `upgrade → downgrade → upgrade` на отдельной базе.
- `app/crud/plan_violation.py` — **new**: запись нарушений с заменой по (день, origin), чтение и конвертер `skeleton_document` — скелет едет в базу через тот же `replace_plan`, что и план человека.
- `app/crud/plan.py` — **mod**: `draft_of(document, on)` — те же подготовленные строки без текста.
- `app/api/day.py` — **mod**: `POST /day/{date}/plan/skeleton`, `GET /day/{date}/plan/violations`; приём плана человеком после записи прогоняет `check_all` и пишет `warn` с `origin='human'`, не отклоняя правку.
- `app/schemas/plan_violation.py` — **new**: `PlanViolationResponse`, `SkeletonRejection`. Поля, в котором мог бы проехать текст пункта, в файле нет.
- `tests/test_day_constraints.py` — **new**: 32 теста, у каждого правила пропуск и отлов; отдельно — что `detail` не несёт текста и что grep не находит в двух модулях ни `16:00`, ни `22:30`, ни `480`.
- `tests/test_day_skeleton.py` — **new**: 19 тестов. Скелет чист против `check_all` на действующей строке, на `legacy` и на строке со сдвинутыми краями; снимок соседних дат до и после вызова сравнивается как значение; правка человека в свободный вечер сохраняется и получает `warn`.

Найдено по ходу: словарь кодов правил приходится писать трижды — в `constraints`, в модели и в миграции. Модель не может импортировать `constraints` (цикл через `app.models`), миграция не имеет права зависеть от кода приложения. Три списка держит вместе тест `test_the_model_and_the_module_name_the_same_rules`.

Проверки: `ruff check` / `ruff format --check` / `mypy --strict` (131 файл), `alembic heads` — одна голова `c8f0a2b4d6e7`, `pytest tests/ -q` — 898 passed на базе `habit_tracker_test_fast1`. `# type: ignore` в новом коде — ноль. Docker не поднимается, `make check` целиком не гонялся.

## 2026-08-31 — PHASE-03/124 отмена тапа и источник отметки

Отмена последнего тапа и распределение отметок по клиентам. Схема не менялась — `source`, `idempotency_key` и `undone_at` приехали с миграцией #121.

- `app/crud/quick_mark.py` — **mod**: `undo_event` (три отказа кодами `already_undone` / `not_last` / `edited_by_hand`), `_journal_still_explains_the_day` (сумма дельт журнала против хранимого числа; для галки — состояние против `bool_value` события), `_previous_tick`, `_drop_relapse_entry`, `source_usage`, `get_event`.
- `app/api/quick_marks.py` — **mod**: `POST /quick-marks/events/{id}/undo` (200 с новым состоянием дня, 404, 409 с причиной) и `GET /quick-marks/events/sources` (распределение тапов по клиентам за период).
- `app/schemas/quick_mark.py` — **mod**: `QuickMarkUndoResponse`, `QuickMarkSourceUsage`.
- `tests/test_quick_mark_undo.py` — **new**: 16 тестов — возврат суммы, галка, `set_value`, три отказа с проверкой хранимого значения после каждого, повтор под одним ключом, отмена `relapse` вместе с её записью, источник каждого события, неизвестный `source`, распределение и его период.
- `tests/conftest.py` — **mod**: фикстуры `water` / `vitamins` / `smoking` переехали сюда из `test_quick_marks.py`: их жмут два тест-модуля, а импорт фикстуры между модулями ловится ruff как F811.
- `tests/test_quick_marks.py` — **mod**: те же три фикстуры убраны, helpers остались.
- `tests/test_insights.py` — **mod**: `date.today()` заменён на `today_local()`. Тест падал между полуночью и границей суток: окно контекста строится по `local_date()`, а запись создавалась на календарное «завтра».

Проверки: `ruff check` / `ruff format --check` / `mypy --strict` (126 файлов) — зелёные; `pytest tests/ -q` — 829 passed на отдельной базе `habit_tracker_test_fast1`. Docker в этой среде не поднимается, поэтому `make check` целиком не гонялся.

## 2026-07-25 — PHASE-01/53 apply-plan batch endpoint

Транзакционный `POST /api/v1/categories/batch`: additive-only план (`create_category` / `add_field`) применяется одной транзакцией, всё-или-ничего. UI онбординга получил чекбоксы и редактирование имени, кнопку «создать» и переход на `/categories`.

Backend (все **mod**, кроме нового кода внутри):

- `app/schemas/category.py` — **mod**: `BatchCreateCategoryOp` / `BatchAddFieldOp` (дискриминатор `op`), `CategoryBatchRequest`, `CategoryBatchResponse`.
- `app/crud/category.py` — **mod**: `apply_category_batch` + `CategoryBatchError`; на отказе явный `rollback`, checklist-guard и дубль-имени как у одиночного POST.
- `app/api/categories.py` — **mod**: ручка `POST /categories/batch`, `CategoryBatchError` -> HTTPException (400/422). Константы checklist перенесены в crud (single source), API их импортирует.
- `tests/test_categories.py` — **mod**: `TestCategoryBatch` (6 тестов: атомарность, дубль имени в БД и внутри плана, add_field в несуществующую категорию, checklist без boolean).

Frontend:

- `frontend/lib/api.ts` — **mod**: `categoriesAPI.applyBatch`, `CategoryBatchResponse`.
- `frontend/app/onboarding/page.tsx` — **mod**: интерактивный предпросмотр (чекбоксы, редактирование имени, apply + redirect); create включён по умолчанию, add_field и конфликты — выключены.
- `frontend/app/onboarding/page.test.tsx` — **new**: дефолты чекбоксов и что снятые операции не уходят на бэкенд.
- 12 sibling test-файлов (`app/**/*.test.tsx`, `hooks/*.test.ts`) — **mod**: в mock `@/lib/api` добавлен `onboardingAPI`, чтобы общий реестр export-имён bun (фиксируется при первом линке) всегда содержал имя; иначе новый линк онбординг-страницы падал в полном прогоне.

Feedback loops: backend `ruff`/`mypy --strict`/`pytest` (172) — green; frontend `tsc`/`eslint`/`bun test` (348) — green, детерминированно на 3 прогонах.

## 2026-07-24 — round 3 review fixes (маркеры + счётчик ревью)

Раунд 3 по замечаниям ревью. Кода backend не менялось, менялись маркеры и репо-скрипт.

- `app/crud/category.py` — маркер уже указывает `PHASE-01/36-category-update-history-loss`, что соответствует описанному изменению (`_sync_category_fields`); ссылки на `PHASE-01/35` в файле нет.
- `../../../bashs/review-status.sh` — **mod**: токены собираются конкатенацией, поэтому строки-определения в самом скрипте больше не попадают в счётчик и файл может дойти до `approved`. Статус файла определяется **первым** маркером (header) через `grep -m1 -o -F`, так что файл с обоими токенами не попадает в обе корзины. Ticket-id маркера — `PHASE-01/40-mobile-shell-toggle-manifest-today`.

**Review-маркеры.** 33 файла, переведённые прошлым раундом в `[review:approved]` без внешнего ревью, возвращены в `[review:need-review]` — включая `app/schemas/category.py` и `tests/test_categories.py`. Артефакта ревью, закрывающего слайсы 35/36/40, нет, поэтому approved-статус не обоснован (CLAUDE.md §9).

**Тикет PHASE-01/57.** Докстринг `_sync_category_fields` ссылается на `issues/PHASE-01/backlog/57-drop-field-identity-fallback.md`; в тикет добавлена секция про silent data loss при id-less PATCH с переименованием поля, ради которой ссылка и стоит.

Feedback loops: pytest 148/148 green (`TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@127.0.0.1:5433/habit_tracker_test`), `ruff check app tests` clean, `mypy --strict app` clean (39 файлов).

## 2026-07-24 — round 2 review fixes (маршрутизация ревью + инфраструктура)

Раунд 2 по замечаниям ревью. Тикет #19 (`19-idea-voice-daily-summary`) снят с работы и возвращён в `issues/PHASE-01/backlog/`: у него нет Acceptance Criteria и Module Map, TDD по нему невозможен — сначала `/grill-me` + `/write-prd`. Взят следующий разблокированный слайс `51-stt-benchmark-on-vps` (перемещён в `in-work/`); дальше по зависимостям 54 → 52 → 53 → 55.

**Маршрутизация ревью.** Ревьюеру передаётся диапазон коммитов `fa04170..HEAD`, а не «незакоммиченное дерево». Соответствие коммит → тикет:

| Коммит | Тикет | Что в нём |
| --- | --- | --- |
| `5e16ee1` | PHASE-01/36 | `_sync_category_fields` сопоставляет поля id-less пейлоада по (имя, тип) |
| `a8d75ed` | `issues/PHASE-01/in-work/40-mobile-shell-toggle-manifest-today.md` | мобильная оболочка, tab bar, PWA-манифест, `/m/today` |

**Прогон тестов воспроизведён.** Прошлая запись «148/148 green» была непроверяемой: локально не было ни postgres, ни docker-демона, и `pytest` падал 109 × `ConnectionRefusedError`. Поднят локальный кластер postgres 16 (homebrew `postgresql@16`, data dir в scratchpad, слушает `127.0.0.1:5433`, роль `habit_user`, БД `habit_tracker_test`); `TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@127.0.0.1:5433/habit_tracker_test` — **148 passed**, цифра подтверждена.

Файлов тронуто: 2 (0 new, 2 mod) в backend + инфраструктура репозитория.

- `app/crud/category.py` — **mod**: докстринг `_sync_category_fields` теперь явно описывает ограничение compat-shim — PATCH без `id`, переименовывающий поле (или меняющий `field_type`), не сопоставляется по (имя, тип), поэтому старое поле удаляется каскадно вместе с `entry_values`, а новое создаётся пустым. Указано, что шим временный и снимается в follow-up PHASE-01/57. Поведение не менялось.
- `SESSION_REVIEW.md` — **mod**: эта секция.
- `../../../bashs/review-status.sh` — **new** (корень репо): скрипт-счётчик из CLAUDE.md §9, которого в репозитории не было. Считает файлы с `[review:need-review]` против `[review:approved]` только среди tracked-файлов (`git ls-files`), `*.md` исключены — CLAUDE.md и команды пишут токены буквально и иначе попадали бы в счётчик. Exit-code 1, пока есть незакрытые. Текущий прогон: need-review 145, approved 33.
- `../../../.gitignore` — **mod**: добавлен `.vscode/` — пустой `.vscode/settings.json` был untracked-мусором, общего конфига редактора репозиторий не несёт.

**Review-маркеры.** После закрытия ревью слайсов 36 и 40 в 33 файлах диапазона `fa04170..HEAD` маркер переведён в `[review:approved]`. Три файла намеренно оставлены в `need-review`, потому что несут незакоммиченные правки этого раунда: `app/crud/category.py`, `../frontend/app/table/page.tsx`, `../frontend/hooks/useToday.ts`.

Feedback loops: pytest 148/148 green (DSN выше), `ruff check app tests` clean, `ruff format --check` clean (52 файла), `mypy --strict app` clean (39 файлов).

## 2026-07-22 — PHASE-01/25-ai-reports-history

Тикет: история AI-отчётов и выбор периода — `GET /api/v1/insights/` (список, новые сверху, превью), `GET /api/v1/insights/{id}` (полный отчёт, 404), страница `/insights`, селектор периода 7/30/90 на Dashboard. Затронуто 10 файлов (2 new, 8 mod; 5 backend + 5 frontend).

Backend:

- `tests/test_insights.py` — **mod**: +4 теста (TDD, сначала красные) — список новые сверху с полями id/period_days/model/created_at/preview и без content, превью обрезано, GET по id возвращает полный отчёт, 404 на несуществующий id.
- `app/crud/insight.py` — **mod**: `list_ai_reports` (order by created_at desc, id desc) и `get_ai_report` (по id, None при отсутствии).
- `app/schemas/insight.py` — **mod**: `InsightListItem` (id, period_days, model, created_at, preview) + константа `PREVIEW_MAX_CHARS = 200`.
- `app/schemas/__init__.py` — **mod**: ре-экспорт `InsightListItem`.
- `app/api/insights.py` — **mod**: `GET /insights/` (список с превью) и `GET /insights/{report_id}` (полный отчёт, 404) — объявлены до POST, path-роут после статического `/`.

Frontend (`services/frontend`):

- `lib/api.ts` — **mod**: `insightsAPI.getAll` / `insightsAPI.getById` + тип `AIReportListItem`.
- `components/InsightMarkdown.tsx` — **new**: минимальный MD-рендерер отчёта, вынесен из Dashboard для переиспользования.
- `app/insights/page.tsx` — **new**: страница истории — карточки отчётов (период, дата, модель, превью), разворачиваемый полный просмотр (discriminated union `ReportView`), empty state со ссылкой на Dashboard.
- `app/page.tsx` — **mod**: селектор периода 7/30/90 (`INSIGHT_PERIOD_OPTIONS`, aria-pressed) у кнопки «Разбор периода», период прокидывается в `insightsAPI.create`, ссылка «История» на `/insights`; локальный `InsightMarkdown` заменён импортом компонента.
- `components/Navigation.tsx` — **mod**: пункт Insights (`/insights`, иконка Sparkles).

Feedback loops: pytest 99/99 green, ruff check + format clean, mypy --strict clean (36 файлов); frontend — tsc --noEmit clean, eslint clean, `bun test` 27/27, `next build` ok (роут `/insights` собран).

## 2026-07-22 — PHASE-01/16-checklist-upsert-today-page

Тикет: идемпотентный upsert для checklist-категорий — `PUT /api/v1/entries/checklist` (body `{category_id, entry_date, values: {field_id: bool}}`), одна запись на (категория, день). Затронуто 5 файлов (1 new, 4 mod).

- `tests/test_checklist.py` — **new**: 5 тестов — первый PUT создаёт, второй обновляет ту же запись (count=1, тот же id), снятие галочки (`"false"`, без дублей), 422 на form-категорию, 404 на несуществующую.
- `app/crud/entry.py` — **mod**: `upsert_checklist_entry` — ищет Entry по (category_id, entry_date), создаёт при отсутствии; boolean-значения (`"true"`/`"false"`) мержатся в существующие EntryValue без дублей.
- `app/schemas/entry.py` — **mod**: `ChecklistUpsertRequest` (`category_id`, `entry_date`, `values: dict[int, bool]`).
- `app/schemas/__init__.py` — **mod**: экспорт `ChecklistUpsertRequest`.
- `app/api/entries.py` — **mod**: endpoint `PUT /entries/checklist` (объявлен раньше `/{entry_id}`-роутов): 404 — категории нет, 422 — категория не checklist, иначе upsert; `app/main.py` не менялся — endpoint живёт в уже подключённом entries-роутере.

Feedback loops: pytest 71/71 green, ruff check + format clean, mypy --strict clean (27 файлов).

## 2026-07-22 — PHASE-01/15-category-display-mode-group

Тикет: категории получают `display_mode` (`form` | `checklist`, default `form`) и `group` (varchar NULL) — схема, модель, Pydantic, API, тесты. Затронуто 5 файлов (1 new, 4 mod).

- `alembic/versions/2026_07_22_1353-0d7b1cb0f163_category_display_mode_group.py` — **new**: reversible миграция `add_column display_mode (server_default 'form', not null)` + `group (nullable)`; upgrade/downgrade прогнаны на dev-БД.
- `app/models/category.py` — **mod**: `display_mode: Mapped[str]` (String(20), default/server_default `form`), `group: Mapped[str | None]` (String(100)).
- `app/schemas/category.py` — **mod**: `CategoryDisplayMode = Literal["form", "checklist"]`; поля добавлены в `CategoryBase` (default `form`) и `CategoryUpdate` (optional); невалидное значение даёт 422 через Pydantic.
- `app/crud/category.py` — **mod**: `create_category` прокидывает `display_mode`/`group` в модель.
- `tests/test_categories.py` — **mod**: +5 тестов (дефолты, create с checklist/Health, patch, 422 на мусорный display_mode в POST и PATCH).

Feedback loops: pytest 66/66 green, ruff check + format clean, mypy --strict clean (27 файлов).

Тикет: миграция backend на стандарты проекта (uv, mypy --strict, ruff). Затронуто ~30 файлов (3 new, 1 удалён, остальные mod).

Инфраструктура:

- `pyproject.toml` — **new**: зависимости из requirements.txt (те же пины) + dev-группа (pytest/mypy/ruff), настройки ruff (py310) и mypy (strict, pydantic-плагин); добавлен `greenlet>=3.0` явно (маркер sqlalchemy пропускает macOS arm64).
- `uv.lock` — **new**: лок-файл, Python пин 3.10 (`.python-version` — **new**).
- `requirements.txt` — **удалён** (заменён pyproject/uv.lock).
- `Dockerfile` — **mod**: сборка через uv (`uv sync --frozen --no-dev`); venv в `/opt/venv`, чтобы bind-mount `/app` из docker-compose его не затенял.

Типизация (без функциональных изменений):

- `app/core/database.py` — **mod**: `declarative_base()` → typed `class Base(DeclarativeBase)`; `get_db` → `AsyncGenerator[AsyncSession, None]`.
- `app/models/{category,field,entry,entry_value,journal}.py` — **mod**: legacy `Column` → SQLAlchemy 2.0 `Mapped[]`/`mapped_column()`, `__repr__ -> str`.
- `app/api/{categories,entries,journal}.py`, `app/main.py` — **mod**: return-аннотации всех endpoint'ов, builtin generics; в journal `items` явно валидируются в `JournalEntryResponse`.
- `app/crud/{category,entry,journal}.py`, `app/schemas/{category,entry,journal}.py` — **mod**: `Optional[X]`/`List[X]` → `X | None`/`list[X]`.
- `tests/conftest.py` — **mod**: `TEST_DATABASE_URL` переопределяется через env (default прежний, docker-host `postgres`); типизированы фикстуры.
- `alembic/env.py` — **mod**: неиспользуемые импорты моделей → `import app.models  # noqa: F401`.
- `seed_data.py` — **mod**: убран лишний f-префикс (F541).
- Форматирование: `ruff format` по всему дереву (21 файл, включая `app/api/table.py`, `app/core/auth.py`, `app/core/config.py`, `app/crud/table.py`, tests — только formatting).

Feedback loops: `uv run mypy --strict app` — 0 ошибок, ни одного `# type: ignore`; `uv run ruff check` + `ruff format --check` чисто; `uv run pytest` 61/61 green (локально, disposable postgres:16 на порту 55432 через `TEST_DATABASE_URL`); docker-образ собирается, `import app.main` в образе — ok.

## 2026-07-21 — PHASE-01/04-backend-table-endpoint (round 2, review fixes)

Правки по замечаниям ревью. Затронуто 5 файлов (0 new, 5 mod).

- `app/crud/table.py` — **mod**: `except ValueError: pass` заменён на `logger.warning("non-numeric value in number field", extra={field_id, entry_id})`; значение поля в лог не пишется (PII-safe). Module-level `logger = logging.getLogger(__name__)`; в `_CellAccumulator.add` добавлен параметр `field_id`.
- `app/api/table.py` — **mod**: named constant `MAX_RANGE_DAYS = 366`; диапазон длиннее лимита → 422 с detail «сколько запрошено / каков максимум» (DoS-guard: каждый день диапазона материализует `TableDay` в памяти). Импорт `TableResponse` переведён на `from app.schemas import ...` по паттерну соседей.
- `app/crud/__init__.py` — **mod**: `table` добавлен в импорты и `__all__` по конвенции пакета.
- `app/schemas/__init__.py` — **mod**: ре-экспорт `TableCell` / `TableDay` / `TableResponse`.
- `tests/test_table.py` — **mod**: +2 теста (TDD, сначала красные): нечисловое значение в number-поле — сумма по валидным + warning в caplog без сырого значения; диапазон длиннее 366 дней → 422.

Feedback loops: pytest 61/61 green (в контейнере `habit_backend`), ruff clean (app + tests), mypy strict clean на файлах тикета. Review-маркеры оставлены `[review:need-review]` до повторного ревью.

## 2026-07-21 — PHASE-01/04-backend-table-endpoint

Тикет: табличное представление с агрегацией за день. Затронуто 5 файлов (4 new, 1 mod).

- `app/schemas/table.py` — **new**: Pydantic DTO `TableResponse` / `TableDay` / `TableCell` (`{days: [{date, cells: [{category_id, field_id, aggregated_value, entry_count}]}]}`).
- `app/crud/table.py` — **new**: агрегация за день через `_CellAccumulator`: number → sum (int-формат для целых), boolean → any (`true`/`1`/`yes`), остальные типы → last по `Entry.created_at` (tie-break по `id`); `entry_count` = число записей с значением поля за день; каждый день диапазона присутствует в ответе (пустой день — `cells: []`).
- `app/api/table.py` — **new**: `GET /api/v1/table?date_from&date_to` (обе даты обязательны, диапазон включительно, 422 при `date_from > date_to`).
- `app/main.py` — **mod**: подключён `table.router` под API-key auth.
- `tests/test_table.py` — **new**: 5 API-тестов (сумма 20+22=42 + entry_count=2, пустой день, boolean any, text last, инклюзивные границы диапазона).

Schema-слой: миграция не понадобилась — индекс по `entries.entry_date` уже есть (`index=True` в модели, создан initial-миграцией).

Feedback loops: pytest 59/59 green (в контейнере `habit_backend`), ruff clean (app + tests), mypy strict clean на трёх новых файлах (легаси-дерево целиком не mypy-clean — вне скоупа, как и в прошлой сессии). Смоук live-endpoint через docker: 200 на пустом диапазоне (попутно применён `alembic upgrade head` в локальной dev-базе — она была пуста, все endpoint-ы отдавали 500).

## 2026-07-21 — PHASE-01/01-backend-api-key-auth

Тикет: API-key auth — все API-роутеры закрыты заголовком `X-API-Key`. Затронуто 10 файлов (2 new, 8 mod).

Основные изменения (суть тикета):

- `app/core/auth.py` — **new**: dependency `require_api_key`; ключ из env `API_KEY`, сравнение через `secrets.compare_digest`; пустой env = auth выключен (dev) с warning; значение ключа не логируется.
- `tests/test_auth.py` — **new**: 5 API-тестов (401 без ключа / с неверным, 200 с верным, dev-режим с warning, ключ отсутствует в логах).
- `app/core/config.py` — **mod**: добавлена настройка `API_KEY` (default пустая строка).
- `app/main.py` — **mod**: dependency подключена ко всем трём роутерам (`categories`, `entries`, `journal`); `/` и `/health` намеренно открыты (docker healthcheck).
- `tests/conftest.py` — **mod**: autouse-фикстура `api_key` (включает auth во всех тестах) и default-заголовок `X-API-Key` у тест-клиента.
- `../../docker-compose.yml` — **mod**: проброс `API_KEY: ${API_KEY:-}` в backend.

Попутные lint-фиксы (ruff, без изменения поведения):

- `app/crud/category.py` — **mod**: `is_active == True` → `is_active.is_(True)`.
- `app/crud/entry.py` — **mod**: убраны неиспользуемые импорты (`datetime`, `Category`).
- `app/models/entry_value.py` — **mod**: убран неиспользуемый импорт `String`.
- `app/schemas/entry.py` — **mod**: убраны неиспользуемые импорты (`Field`, `Dict`, `Any`).

Feedback loops: pytest 54/54 green (в контейнере `habit_backend`), ruff clean (app + tests), mypy strict clean на `auth.py`/`config.py`, mypy clean на новых/изменённых тестах (легаси-дерево целиком не mypy-clean — вне скоупа тикета).

## 2026-07-22 — PHASE-01/17-table-groups-sport-columns

Тикет: table view — метаданные категорий (group, display_mode, primary field) в ответе `GET /api/v1/table` для вкладок-групп и колонок-категорий на фронте. Затронуто 4 файла (0 new, 4 mod).

- `app/schemas/table.py` — **mod**: новый DTO `TableCategoryMeta` (id, name, display_mode, group, primary_field_id/name/type); `TableResponse` дополнен полем `categories`.
- `app/crud/table.py` — **mod**: `_get_category_metas` (активные категории + selectinload полей, сортировка по имени) и `_category_meta` (primary field = первое поле по `(order, id)`, у категории без полей — None); агрегация по дням не менялась.
- `app/schemas/__init__.py` — **mod**: re-export `TableCategoryMeta`.
- `tests/test_table.py` — **mod**: 3 новых API-теста (`TestTableCategoryMeta`): группы Sport/Sport/None проходят насквозь, primary = первое поле по order (не по порядку создания), категория без полей — primary None. Новые тесты типизированы под mypy --strict.

Schema-слой: миграция не нужна — колонки `display_mode`/`group` добавлены тикетом #15.

Feedback loops: pytest 74/74 green (локально, TEST_DATABASE_URL → localhost:5433), ruff clean, `mypy app` clean (легаси-долг в `seed_data.py`/тестах — 117 ошибок до и после, ноль новых).

## 2026-07-22 — PHASE-01/18-table-checklist-columns-backfill

Тикет: table checklist-режим — API-тесты бэкфилла (upsert на прошлую дату отражается в GET /table). Backend-код не менялся (переиспользуются #16 upsert и #17 table). Затронут 1 файл (0 new, 1 mod).

- `tests/test_checklist.py` — **mod**: 2 новых теста (`test_backfill_past_date_visible_in_table`, `test_backfill_uncheck_past_date_visible_in_table`) — PUT checklist на прошлую дату (today-2) даёт cell `aggregated_value: true` в GET /table, повторный PUT со значением false переворачивает ячейку без дубликатов. Новые тесты полностью типизированы (`-> None`, `checklist_category: dict[str, Any]`).

Feedback loops: pytest 77/77 green (локально, TEST_DATABASE_URL → localhost:5433), ruff clean; `mypy tests/test_checklist.py` — 15 ошибок, все легаси (фикстуры и старые тесты, baseline без изменений), от диффа тикета новых ошибок ноль.

## 2026-07-22 — PHASE-01/24-ai-insights-endpoint-button

Тикет: AI-инсайты end-to-end — app/llm/ (anthropic, claude-sonnet-5), таблица ai_reports, POST /api/v1/insights/, кнопка «Разбор периода» на Dashboard. Живой прогон ждёт ANTHROPIC_API_KEY; имплементация и тесты — на моках. Затронуто 13 файлов backend (8 new, 5 mod) + 2 файла frontend (0 new, 2 mod).

Backend new:
- `app/llm/__init__.py` — **new**: пакет LLM-оркестрации, единственное место с импортом anthropic.
- `app/llm/client.py` — **new**: `InsightsClient` (интерфейс, mock-boundary для тестов) + `AnthropicInsightsClient` (AsyncAnthropic, claude-sonnet-5, timeout 120s); `LLMError` — маппинг ошибок SDK без утечки контента/ключа в сообщения.
- `app/llm/context.py` — **new**: `build_period_context` — агрегаты table-логики (имена категорий/полей резолвятся) + тексты журнала за период; лимит 200 записей журнала.
- `app/llm/prompts.py` — **new**: системный промпт (тренды/пропуски/корреляции/2-3 рекомендации, ответ на русском).
- `app/models/ai_report.py` — **new**: модель AIReport (id, period_days, content, model, created_at).
- `app/schemas/insight.py` — **new**: InsightRequest (period_days default 30, 1..366) и InsightResponse.
- `app/crud/insight.py` — **new**: create_ai_report.
- `app/api/insights.py` — **new**: POST /insights/ — 503 без ключа (dependency `get_llm_client` -> None), 502 на LLMError (ничего не сохраняем), 201 + сохранённый отчёт.
- `alembic/versions/2026_07_22_1600-3f2a9c1b7e44_ai_reports_table.py` — **new**: reversible миграция ai_reports (проверена upgrade/downgrade/upgrade на dev-БД).

Backend mod:
- `app/core/config.py` — **mod**: ANTHROPIC_API_KEY="" (пустой = фича off).
- `app/main.py` — **mod**: подключён insights router под API-key auth.
- `app/models/__init__.py`, `app/schemas/__init__.py` — **mod**: re-export AIReport / Insight-схем.
- `pyproject.toml` — **mod**: + anthropic (uv add).
- `tests/test_insights.py` — **new**: 6 тестов — happy path (отчёт сохранён), 503 без ключа, 502 на исключение клиента (ничего не сохранено), дефолт 30 дней, unit-тесты build_period_context (таблица+журнал в контексте, период в тексте). Мок на границе app/llm через dependency override.

Frontend mod:
- `lib/api.ts` — **mod**: insightsAPI.create (POST /insights/) + тип AIReport.
- `app/page.tsx` — **mod**: панель AI-разбора на Dashboard — кнопка «Разбор периода», неоновый лоадер (ping + glow), минимальный MD-рендер отчёта без новых зависимостей, ошибка с кнопкой Retry.

Feedback loops: pytest 83/83 green (локально, TEST_DATABASE_URL → localhost:5433), ruff check + format clean, mypy --strict app clean, eslint clean, next build green. `grep -r "import anthropic" app/ | grep -v app/llm/` — пусто.

## 2026-07-22 — PHASE-01/26-llm-cli-backend

Файлов тронуто: 6 (2 new, 4 mod).

Backend:
- `app/llm/cli.py` — **new**: CliInsightsClient — `claude -p --output-format text` через asyncio.create_subprocess_exec, промпт в stdin (без argv-лимитов), таймаут с kill процесса; exit!=0 / таймаут / отсутствие бинаря / пустой stdout → LLMError без содержимого промпта/ответа в сообщении.
- `app/llm/client.py` — **mod**: resolve_insights_client — выбор бэкенда по LLM_BACKEND (`cli` | `api`), пустой = auto (cli при пустом ANTHROPIC_API_KEY и найденном бинаре, иначе api); None = фича off (503).
- `app/core/config.py` — **mod**: LLM_BACKEND (Literal "", "cli", "api"; дефолт "" = auto).
- `app/api/insights.py` — **mod**: get_llm_client делегирует resolve_insights_client; 503-detail стал backend-agnostic.
- `tests/test_llm_cli.py` — **new**: 12 тестов — CliInsightsClient с моком subprocess (успех + argv/stdin, exit!=0 без утечки контента, таймаут с kill, FileNotFoundError, пустой stdout) + 7 тестов выбора бэкенда (explicit cli/api, auto, недоступность → None/503).
- `tests/test_insights.py` — **mod**: 503-тест теперь явно форсит `LLM_BACKEND=api` (auto-детект подхватил бы локальный claude CLI); добавлены return-аннотации (mypy strict).

Feedback loops: pytest 95/95 green (TEST_DATABASE_URL → localhost:5433), ruff clean, mypy clean на всех файлах тикета (репо-wide mypy красный из-за pre-existing долга в нетронутых test_table/test_journal/test_categories/seed_data и др.). Живой прогон на dev-Mac: resolve → CliInsightsClient при пустом ключе, реальный `claude -p` вернул отчёт.

## 2026-07-22 — PHASE-01/27-streak-mode-endpoint

Файлов тронуто: 12 (6 new, 6 mod).

Backend new:
- `app/crud/streak.py` — **new**: расчёт стрика по всей истории категории. `is_relapse_value` (boolean true / number > 0 = срыв; number 0, пустое значение, прочие типы = чисто), чистая `compute_streak(entry_dates, relapse_dates, today)` (день без записи = чистый, current = хвостовой ран, best = максимальный) и `get_category_streak` с одним SQL-джойном Entry/EntryValue/Field.
- `app/schemas/streak.py` — **new**: `StreakResponse` (category_id, streak_mode, current_streak, best_streak, last_relapse_date).
- `alembic/versions/2026_07_22_1830-5b3d8c9a1f27_category_streak_mode.py` — **new**: reversible миграция `categories.streak_mode` VARCHAR(20) NOT NULL DEFAULT 'build' (SQL проверен offline через `alembic upgrade --sql`).
- `tests/test_streak.py` — **new**: 14 тестов — create/patch streak_mode + 422 на мусор, шесть unit-кейсов compute_streak (пустая история, чистая история, срыв сбрасывает current но не best, срыв сегодня → 0, дни без записей не рвут серию, последний срыв из нескольких), 404 на несуществующую категорию, RMO-кейс «Quantity 0 не рвёт серию», срыв по number>0 и boolean true.

Backend mod:
- `app/models/category.py` — **mod**: колонка `streak_mode` (default/server_default 'build').
- `app/schemas/category.py` — **mod**: `CategoryStreakMode = Literal["build","avoid"]`, поле в CategoryBase (дефолт build) и CategoryUpdate.
- `app/crud/category.py` — **mod**: create_category прокидывает streak_mode.
- `app/api/categories.py` — **mod**: `GET /categories/{id}/streak` — 404 на несуществующую категорию, иначе StreakResponse.
- `app/crud/__init__.py`, `app/schemas/__init__.py` — **mod**: re-export streak-модуля и StreakResponse.

Frontend new:
- `lib/streak-format.ts` + `lib/streak-format.test.ts` — **new**: чистые хелперы `formatDays` (1 day / N days) и `formatLastRelapse` (ISO → «5 Mar 2026», null → «never», парс в UTC чтобы день не съезжал по таймзоне) + 4 unit-теста.
- `components/StreakCard.tsx` — **new**: блок «Current streak / Best / Last relapse».

Frontend mod:
- `lib/api.ts` — **mod**: тип `CategoryStreakMode`, `streak_mode` в Category/CategoryCreate, интерфейс `CategoryStreak`, `categoriesAPI.getStreak`.
- `app/categories/page.tsx` — **mod**: select «Streak mode» в редакторе категории + бейдж Avoid на карточке.
- `app/categories/[id]/page.tsx` — **mod**: догружает стрик в общий Promise.all, StreakCard рендерится только для `streak_mode === 'avoid'`.
- `lib/category-nav.test.ts` — **mod**: фикстура категории дополнена streak_mode (иначе tsc красный).

Feedback loops: pytest 113/113 green (`TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5433/habit_tracker_test` — пользователь `habit_user`, не `postgres`), ruff check + format clean, `mypy app` clean и `mypy tests/test_streak.py` clean (репо-wide mypy остаётся красным из-за pre-existing долга в нетронутых test_table/test_journal/test_categories/seed_data), bun test 37/37 green, tsc clean, eslint clean, next build green.

## 2026-07-22 — PHASE-01/27-streak-mode-endpoint (round 2, review fixes)

Файлов тронуто: 6 (2 new, 4 mod).

- `app/crud/values.py` — **new**: общий слой интерпретации EAV-значений. `BOOLEAN_TRUE_VALUES`, `is_true_value(value)` и `parse_number(value, *, field_id, entry_id)`. Пустое/whitespace-значение — тихий `None` без warning: EntryForm шлёт `''` за каждое нетронутое поле, раньше это лило шум в лог на каждом расчёте стрика. Непарсящийся непустой текст по-прежнему логируется warning'ом, само значение в лог не попадает (PII-safe), только `field_id`/`entry_id`.
- `tests/test_crud_values.py` — **new**: 14 unit-тестов — токены true (регистр/пробелы), falsy-значения, парсинг int/float/отрицательных, «пустое → None без записи в лог» (через caplog), «непарсящееся → None + ровно один warning без значения в тексте».
- `app/crud/table.py` — **mod**: удалена локальная копия `BOOLEAN_TRUE_VALUES` и try/except ValueError в `_CellAccumulator.add`; теперь `is_true_value`/`parse_number`. Локальный `logger` и импорт `logging` больше не нужны.
- `app/crud/streak.py` — **mod**: удалена вторая копия `BOOLEAN_TRUE_VALUES` и ручной `float()`; `is_relapse_value` сведён к `is_true_value(...)` для BOOLEAN и `(parse_number(...) or 0) > 0` для NUMBER. Граница суток зафиксирована как UTC — `datetime.now(timezone.utc).date()` вместо `date.today()`, согласованно с `lib/streak-format.ts`, который парсит ISO-дату как UTC; решение отражено в docstring `get_category_streak`.
- `app/api/categories.py` — **mod**: docstring `GET /categories/{id}/streak` явно фиксирует, что до #23 расчёт всегда в avoid-семантике, а `streak_mode` в ответе — эхо колонки категории и на числа не влияет; для build-категорий числа бессмысленны, UI обязан прятать блок.
- `SESSION_REVIEW.md` — **mod**: исправлен DSN в feedback loops раунда 1 — `habit_user:habit_pass@localhost:5433`, пользователь `postgres` был указан ошибочно.

Feedback loops (`TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5433/habit_tracker_test`): на момент завершения правок pytest был 131/131 green; ruff check + format clean, `mypy --strict app` clean (39 файлов), `mypy --strict tests/test_crud_values.py tests/test_streak.py` clean.

ВНИМАНИЕ: во время сессии в тот же worktree параллельно писала другая сессия — в `app/api/{entries,insights,journal,table,categories}.py` появилось снятие trailing slash у роутов (`@router.get("/")` → `@router.get("")`), в `next.config.ts` — `allowedDevOrigins`. Эти изменения не мои и не входят ни в один из трёх коммитов ниже. Из-за них repo-wide pytest сейчас красный (23 падения в `test_journal`/`test_checklist`/`test_entries`/`test_insights` — тесты ещё ходят на старые URL с завершающим слэшем). Тесты в границах этого тикета зелёные: `pytest tests/test_crud_values.py tests/test_streak.py tests/test_table.py tests/test_categories.py` — 62/62 green.

## 2026-07-23 — PHASE-01/31 checklist-валидация: 422 без boolean-поля

Файлов тронуто: 2 (0 new, 2 mod).

- `app/api/categories.py` — **mod**: POST `/categories` с `display_mode=checklist` без boolean-поля в `fields` и PATCH, переводящий категорию в `checklist`, когда у неё нет boolean-полей, возвращают 422 с подсказкой добавить boolean-поле. Валидация в API-слое (`_ensure_checklist_has_boolean_field`), т.к. для PATCH нужны загруженные поля категории; отклонённый PATCH не меняет категорию.
- `tests/test_categories.py` — **mod**: 3 новых теста (422 на create с не-boolean полями, 422 на create без полей, 422 на patch + проверка что категория не изменилась); 2 существующих теста обновлены под новое правило — теперь создают boolean-поле перед включением checklist.

Feedback loops: pytest 138/138 green, `mypy --strict app` clean, `ruff check` + `ruff format --check` clean.

## 2026-07-23 — PHASE-01/39 server idempotency-key на POST /entries

Файлов тронуто: 5 (2 new, 3 mod).

- `app/models/entry.py` — **mod**: добавлена nullable unique-колонка `idempotency_key: Mapped[str | None]` (String(255), unique+index). Single-user app, поэтому глобальная уникальность достаточна (user-скоупа пока нет). NULL-строки не констрейнятся в Postgres — keyless-создание остаётся неограниченным.
- `app/crud/entry.py` — **mod**: `create_entry(db, entry, idempotency_key=None)` персистит ключ; новый `get_entry_by_idempotency_key(db, key)` для дедупа повторов.
- `app/api/entries.py` — **mod**: `POST /entries` читает заголовок `Idempotency-Key`. Если по ключу уже есть запись — возвращает её с HTTP 200 без создания дубля; первое создание — 201. Гонка параллельного повтора ловится через `IntegrityError` (unique-констрейнт как backstop): rollback + повторное чтение победителя.
- `alembic/versions/2026_07_23_1900-b2d4e6f8a1c3_entries_idempotency_key.py` — **new**: reversible-миграция, add_column + unique-index; down_revision = a1c2d3e4f5a6. Проверена upgrade/downgrade на scratch-БД; `alembic check` не показывает дрейфа по entries (пред-существующий дрейф по is_active/is_required/order не мой).
- `tests/test_idempotency.py` — **new**: 3 теста — повтор с тем же ключом → 200 + тот же id, без дубля в листинге; разные ключи → две записи; без заголовка → обычное создание каждый раз.

Feedback loops (`TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5433/habit_tracker_test`): pytest 142/142 green, `mypy --strict app` clean (39 файлов), `ruff check app tests` clean. Миграция upgrade+downgrade проверены на отдельной БД.

## 2026-07-23 — PHASE-01/35 category-fields-update (баг «не работает update»)

Файлов тронуто: 4 (0 new, 4 mod).

- `app/schemas/category.py` — **mod**: новый `FieldUpsert(FieldBase)` с опциональным `id`; `CategoryUpdate.fields: list[FieldUpsert] | None = None`. `None` = поля не трогаем; список (в т.ч. `[]`) = desired-state.
- `app/crud/category.py` — **mod**: `update_category` теперь diff-синхронизирует поля через `_sync_category_fields`: существующие (по `id`) обновляются на месте → **entry_values не теряются**; поля без id создаются; отсутствующие удаляются каскадно. Скаляры патчатся как раньше (`exclude={"fields"}`). `field_type` приводится к `FieldType(...)` (mypy strict).
- `app/api/categories.py` — **mod**: PATCH-валидация checklist считает **результирующий** набор полей (`category_update.fields` если прислан, иначе `existing.fields`) — теперь можно переключить в checklist и добавить boolean-поле одним запросом.
- `tests/test_categories.py` — **mod**: +5 тестов (rename/add/remove по id; сохранение истории entry_values при переименовании; PATCH без `fields` не трогает поля; checklist+boolean одним PATCH).

Корень бага: `CategoryUpdate` не содержал `fields`, Pydantic молча их выкидывал → правки полей не сохранялись (PATCH 200, но no-op). Требует парного фикса на фронте (слать `id`).

Feedback loops: pytest 146/146 green, `mypy --strict app` clean (39 файлов), `ruff check app tests` + `format --check` clean.

## 2026-07-24 — PHASE-01/36 category-update-history-loss (записи затираются после update категории)

Файлов тронуто: 3 (0 new, 3 mod).

- `app/crud/category.py` — **mod**: `_sync_category_fields` сопоставляет поля в два прохода: сначала по `id`, затем по паре (имя, тип) среди незанятых полей. Пейлоад без `id` (старая сборка фронта, сторонний клиент) больше не пересоздаёт поля и не уносит `entry_values` каскадом. Удаление осталось явным: поле, не сопоставленное ни по id, ни по (имя, тип), удаляется.
- `tests/test_categories.py` — **mod**: +2 теста — PATCH без id сохраняет id полей и историю значений; PATCH без id по-прежнему удаляет поле, которого нет в пейлоаде.
- `../frontend/app/table/page.tsx` — **mod**: рефетч таблицы на `visibilitychange`/`focus`/`pageshow` — в PWA страница не перезагружается, и запись, добавленная на `/today`, не появлялась в таблице до ручного релоада.

Корень бага в проде: бэкенд с фиксом #35 задеплоен, а сборка фронта на VPS — старая (в чанке `fields.map(e=>({name:e.name,field_type:...}))`, без `id`). Каждый PATCH категории удалял все поля и создавал заново → `entry_values` уходили каскадом. Следы в проде: категория `Alcohol` без полей, запись Meditation от 2026-07-23 с пустым `values`.

Feedback loops (`TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5433/habit_tracker_test`): pytest 148/148 green, `ruff check app tests` clean, `mypy --strict app` clean (39 файлов). Прогон выполнен против реальной локальной postgres на порту 5433 — прежняя запись про «нет доступной postgres» была ошибочной (искали на 5432).

## 2026-07-24 — PHASE-01/40 закрытие блокеров дуального ревью (backend-часть)

Файлов тронуто: 2 (0 new, 2 mod).

- `app/crud/category.py` — **mod**: заведён `logger = logging.getLogger(__name__)` по образцу `app/crud/values.py`. Логируются две ветки `_sync_category_fields`: `warning` при удалении поля, не сопоставленного ни по `id`, ни по (имя, тип) — вместе с ним каскадом уходят `entry_values`; `info` при срабатывании compat-shim по идентичности. В лог идут только `category_id` и `field_id` — имена полей задаёт пользователь («Вес», «Настроение»), это PII по §6 CLAUDE.md, поэтому в сообщение они не попадают. Докстринг `_sync_category_fields` больше не утверждает, что потеря истории происходит «молча».
- `tests/test_categories.py` — **mod**: +1 тест `test_dropping_a_field_with_history_is_logged` — id-less PATCH с переименованием поля, у которого есть `entry_values`, обязан оставить `warning` в логе; тест дополнительно проверяет, что имя поля в лог **не** попало.

Расхождение с формулировкой ревью: ревьюер просил логировать `field.name`. Не сделано намеренно — §6 запрещает PII в логах, а имя поля вводит пользователь. Диагностическая ценность сохранена: `category_id` + `field_id` однозначно идентифицируют запись.

Feedback loops (`TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5433/habit_tracker_test`): pytest 149/149 green, `ruff check app tests` clean, `mypy app` clean (39 файлов).

## 2026-07-25 — PHASE-01/52 text→additive-only category plan (LangChain, ADR-0006)

Первый вертикальный срез голосового конструктора без голоса: вставил текст — увидел валидированный additive-only план того, что будет создано (не персистится).

- `app/llm/client.py` — **mod**: нейтральный `LLMClient.generate(prompt) -> str` над обоими бэкендами (API + CLI), по ADR-0006.
- `app/llm/cli.py` — **mod**: CLI-бэкенд под нейтральный интерфейс.
- `app/llm/onboarding.py` — **new**: промпт с контекстом существующих категорий, JSON-парсинг, семантическая валидация, один ремонтный заход, флаги конфликта имён.
- `app/schemas/onboarding.py`, `app/api/onboarding.py` — **new**: `POST /api/v1/onboarding/draft`. 503/502/200. Транскрипт и текст ошибки валидации в логи не попадают.
- `app/crud/category.py` — **mod**: вынесен чистый предикат `checklist_has_boolean_field`, общий для categories API и onboarding-валидации.
- `tests/test_onboarding.py` — **new**: parse/validate/conflict + API (503/200/repair/502/conflict/нет-транскрипта-в-логах).

Довод вручную после APPROVE: закрыт warning — `LLMError` в endpoint утекал как 500, добавлена ветка `except LLMError -> 502` (как в `insights.py`), тест написан красным. Scope-creep #53 (claude CLI в Dockerfile/compose, удаление deploy job в ci.yml) откачен к HEAD.

Feedback loops: pytest 166/166, ruff/mypy clean (42 файла); frontend bun test 345/345, tsc/eslint clean.

## 2026-07-25 — PHASE-01/57 снят fallback-сопоставление полей по (имя, тип)

Убран compat-shim из `_sync_category_fields`: id-less клиент раскатан на VPS (тикет 48), сопоставление полей теперь только по `id`. Поведение предсказуемо — элемент без `id` всегда создаётся как новое поле, никаких неявных match-ей по имени.

- `app/crud/category.py` — **mod**: удалён второй проход и `_identity_key`, докстринг `_sync_category_fields` переписан под id-only.
- `app/schemas/category.py` — **mod**: докстринг `FieldUpsert` очищен от упоминания fallback.
- `tests/test_categories.py` — **mod**: fallback-тест заменён на `test_update_without_ids_creates_new_fields` (id-less пейлоад создаёт новое поле, новый id); тест сохранения истории при пейлоаде с `id` остался.

Feedback loops: pytest test_categories 36/36, ruff clean, mypy clean.

## 2026-07-30 — PHASE-01/73 разбор дня: текст → числовые метрики → предпросмотр → применение

Первый срез разбора дня. Прошит весь путь на одной ветке данных: текст + дата → каталог категорий с идентификаторами → план числовых записей → применение одной транзакцией. Журнал (#74) и чек-лист (#75) не входят.

- `app/models/transcript.py` — **new**: таблица `transcripts` (`id`, `source`, `text`, `created_at`). `source` — обычная строка, а не enum: новая фича добавляет значение, а не мигрирует тип. Урезанная версия таблицы из #54 — аудио здесь нет.
- `alembic/versions/2026_07_30_1500-d4f6a8b0c2e5_transcripts_table.py` — **new**: reversible; проверено `upgrade` → `downgrade` → `upgrade` на dev-базе.
- `app/schemas/daily_summary.py` — **new**: план write-only по построению — операции удаления/переименования/смены типа в схеме отсутствуют, а не «не генерируются». `extra="forbid"`, `category_id`/`field_id` обязательны.
- `app/crud/daily_summary.py` — **new**: семантическая валидация (категория существует, поле — её собственное, тип числовой) и применение одной транзакцией. Метрики одной категории делят одну запись за дату. Тексты ошибок собираются из одних id: они возвращаются наружу и уходят в ремонтный промпт, а формулировка пользователя — это его день.
- `app/llm/daily_summary.py` — **new**: каталог с `category_id`/`field_id` (только числовые поля — в остальные метрику всё равно не записать), парсинг JSON из ответа, один ремонтный заход, 502 на второй провал.
- `app/api/daily_summary.py` — **new**: `POST /daily-summary/draft` (503 без бэкенда, 502 на сбое) и `POST /daily-summary/apply` (201, 400 на неверных id).
- `app/api/deps.py` — **new**: общий `get_llm_client`. Вторая копия зависимости означала бы тест, который мокает модель для одной ручки и ходит в реальный бэкенд из другой; `app/api/onboarding.py` — **mod**: импортирует и ре-экспортирует её, поэтому существующие оверрайды по старому пути продолжают работать.
- `app/main.py`, `app/models/__init__.py`, `app/crud/__init__.py`, `app/schemas/__init__.py` — **mod**: регистрация роутера и ре-экспорты.
- `tests/test_daily_summary.py` — **new**, 27 тестов: парсинг (в т.ч. метрика без `field_id` и «деструктивная» операция отвергаются схемой), каталог с id, валидация по всем веткам, draft (503/200/ремонт/502/сбой бэкенда), транскрипт сохранён с `source='daily_summary'` и отсутствует в логах, apply (одна запись на категорию, падение на середине не оставляет ни одной записи, безопасный повтор, текст ошибки без формулировок пользователя).

Feedback loops (`TEST_DATABASE_URL=...@localhost:5433/habit_tracker_test`): pytest 206/206 green, `ruff check app tests` clean, `ruff format --check` clean, `mypy --strict app` clean (48 файлов).

## 2026-07-30 — PHASE-01/73 раунд 2: правки по ревью

Ревью завернуло первый заход. Поведение фичи не менялось, менялись места, где живёт логика, и явность рисков.

- `app/llm/plan_flow.py` — **new**: общий JSON-план-поток обеих LLM-фич — `extract_json`, `parse_json_plan(text, model_cls, error_cls)` (generic по `TypeVar` от `BaseModel`), `generate_with_repair` и база `PlanError`. Ремонтный заход был скопирован в двух модулях; теперь он один.
- `app/llm/daily_summary.py`, `app/llm/onboarding.py` — **mod**: копии `_extract_json`/`parse_plan`/`build_repair_prompt`/цикла ремонта удалены, оба ходят в `plan_flow`. Тесты обоих модулей мокают границу `LLMClient` и остались без правок — это и было проверкой, что вынос ничего не сдвинул.
- `app/llm/daily_summary.py` — **mod**: в промпте явное правило про `duration` — значение хранится в целых секундах и конвертирует его модель («40 минут» → `2400`). Без правила модель отдавала 40 в поле, которое считает секунды. Тест на присутствие правила в `DAILY_SUMMARY_SYSTEM_PROMPT`.
- `app/crud/values.py` — **mod**: `format_number` — единственное место, где число превращается в текст EAV-колонки (`repr` заменён на `str`, целое теряет дробный хвост). `app/crud/daily_summary.py` и `app/crud/table.py` — **mod**: оба зовут его, правило форматирования перестало быть двумя копиями.
- `app/crud/transcript.py` — **new**: `save_transcript` переехал из фичи в свой модуль — таблица `transcripts` объявлена общей для всех текстовых фич, за фичей остался только дискриминатор `DAILY_SUMMARY_SOURCE`. `app/crud/__init__.py` — **mod**: ре-экспорт.
- `app/crud/daily_summary.py` — **mod**: комментарий у `rollback()` переписан — утверждение «сессия из зависимости сама не откатывается» было ложным (`get_db` откатывает на любом исключении). Настоящая причина оставить `rollback()`: вызывающий ловит `DailySummaryApplyError` и продолжает пользоваться сессией.
- `app/schemas/daily_summary.py` — **mod**: `DailySummaryDraftRequest.entry_date` перестал быть принимаемым-и-неиспользуемым — дата уходит в `build_prompt`, а промпт получил правило про относительные даты («вчера»/«утром» — время внутри дня, а не другая дата).
- `app/api/onboarding.py` — **mod**: убран дублирующийся review-заголовок (два маркера считались `review-status.sh` дважды).

**Принятый риск.** `POST /daily-summary/apply` не принимает `Idempotency-Key`, в отличие от `POST /entries` (#39). Повтор после ошибки безопасен — транзакция всё-или-ничего, ничего не записано. Повтор после **успеха** (двойной клик, ретрай по таймауту, возврат на экран с тем же планом) создаёт вторые записи за ту же дату, и table их суммирует. Риск принят на этом срезе, цена — ручное удаление лишних записей через Entries; закрытие внесено в acceptance #74 отдельным пунктом.

## Тикет 74 — журнальная запись дня и идемпотентный apply

Дата 2026-07-30. У разобранного дня появился текст, и он едет той же транзакцией, что и метрики. Главное здесь не генерация, а коллизия: `GET /journal/date/{entry_date}` уже подразумевает «запись дня», но ничто не мешало создать вторую.

**Кто решает коллизию.** Не модель: есть ли запись за дату — факт базы, а не пересказа. `POST /daily-summary/draft` смотрит на дату сам и отдаёт клиенту готовую операцию — `mode="append"` с id найденной записи или `mode="create"`. Режим `replace` драфт не выдаёт никогда: это единственный путь, теряющий написанное, и включает его только пользователь.

**Что делает apply.** `write_day_journal` трактует `mode` как намерение, а не команду, потому что между предпросмотром и кнопкой день мог измениться: записи нет — создаём (в том числе для `append`); есть и `replace` — заменяем; есть в любом другом режиме — дописываем через `DAY_JOURNAL_SEPARATOR`. Поэтому `create` по устаревшему предпросмотру второй записи за день не создаёт. Заголовок при дописывании не трогаем, настроение и теги заполняем только пустые — иначе проставленное руками молча стёрлось бы.

**Атомарность.** Журнал пишется последним и в той же транзакции; `except` в `apply_daily_summary` расширен с `DailySummaryApplyError` до любого исключения — иначе падение на журнале оставило бы записанные метрики без текста дня. Исключение пробрасывается как есть.

**Идемпотентность (закрывает принятый риск #73).** `POST /daily-summary/apply` принимает `Idempotency-Key`. Схема не менялась, поэтому ключ раскладывается по уже существующей уникальной колонке `entries.idempotency_key`: на запись категории ложится `"<key>:<category_id>"`, и повтор с тем же телом вычисляет тот же набор ключей, находит записи и отвечает 200 исходным результатом, ничего не записывая — в том числе не дописывая пересказ второй раз. Слепая зона названа в докстринге `find_applied_summary`: apply одного лишь журнала (без метрик) ключом не дедуплицируется, его страхует только коллизия за дату.

- `app/schemas/daily_summary.py` — **mod**: `JournalDraft` (то, что пишет модель), `JournalOp` (+ `mode`/`existing_entry_id`), `DailySummaryDraftResponse`; `metrics` в apply перестал быть обязательным, вместо `min_length=1` — валидатор «хоть что-то одно»; в ответе появился `journal_entry_id`.
- `app/crud/journal.py` — **mod**: `get_day_journal_entry` (самая ранняя запись за дату — это утренние заметки) и `write_day_journal` без коммита, транзакцией владеет вызывающий.
- `app/crud/daily_summary.py` — **mod**: запись журнала внутри транзакции, `entry_idempotency_key`, `find_applied_summary`, откат на любом исключении.
- `app/api/daily_summary.py` — **mod**: draft достраивает журнальную операцию до коллизии, apply принимает заголовок и отвечает 200 на повтор (включая гонку через `IntegrityError`).
- `app/llm/daily_summary.py` — **mod**: в промпте объект `journal` (Markdown-проза) и правило «журнал пересказывает, а не додумывает»; неправдоподобное пишется как сказано и помечается.
- `tests/test_daily_summary.py` — **mod**: дописывание/создание/замена, отсутствие второй записи за день, откат метрик при падении журнала, режим в драфте, повтор по ключу.

Feedback loops: `pytest` 225/225 green, `ruff check` clean, `mypy` — новых ошибок нет (остаются прежние в `seed_data.py` и старых тест-файлах).

## 2026-07-30 — PHASE-01/74 раунд 2: правки по ревью

Ревью завернуло первый заход двумя блокерами. Поведение изменилось в одном месте — идемпотентность теперь покрывает apply без метрик, — остальное про то, где живёт логика.

**Отступление от тикета.** Пункт «Schema: без изменений» нарушен осознанно: без носителя ключа acceptance «повторное применение не создаёт вторых записей» невыполним для apply одного лишь журнала. Добавлена обратимая миграция `e5a7b9c1d3f6` с таблицей `applied_daily_summaries`.

**Блокер 1 — идемпотентность journal-only apply.** Ключ переехал с созданных записей на сам факт применения дня.

- `app/models/applied_daily_summary.py` — **new**: `AppliedDailySummary` (`idempotency_key` UNIQUE NOT NULL, `entry_date`, сохранённый ответ `entry_ids`/`journal_entry_id`, `created_at`). У `journal_entry_id` нет FK намеренно: удаление записи журнала не должно стирать факт применения, иначе ключ станет переиспользуемым и пересказ запишется второй раз.
- `alembic/versions/2026_07_30_1800-e5a7b9c1d3f6_applied_daily_summaries.py` — **new**: обратимая миграция; `upgrade`/`downgrade`/`upgrade` прогнаны на локальной БД.
- `app/crud/daily_summary.py` — **mod**: строка-квитанция пишется в той же транзакции, что метрики и журнал; `find_applied_summary` ищет по `applied_daily_summaries`, а не по `Entry.idempotency_key.in_(...)`, и при `metrics == []` возвращает прежний результат **до** вызова `write_day_journal`. Ответ отдаётся из сохранённых полей, поэтому исходные `entry_ids` и их порядок совпадают байт-в-байт.
- `tests/test_daily_summary.py` — **mod**: `TestJournalOnlyIdempotency` — два apply с `metrics=[]` и одним ключом, режимы `create` и `append`; проверяется 200 с теми же id, одна запись в журнале, `DAY_JOURNAL_SEPARATOR` не появился (create) / встретился ровно один раз (append).

**Блокер 2 — инверсия зависимостей.** `app/crud/journal.py` — **mod**: импорт `from app.schemas.daily_summary import JournalOp` удалён, нижний слой больше не знает про DTO фичи. Сигнатура — `write_day_journal(db, entry_date, *, mode, title, content, mood, tags)`. Распаковка `JournalOp` и выбор режима переехали в `app/crud/daily_summary.py::resolve_journal_mode` (там же правило «`create` при существующей записи = `append`»). `DAY_JOURNAL_SEPARATOR` остался в `journal.py`: им пользуется нейтральный `_appended`.

**Warnings.**

- Полнота набора ключей. `find_applied_summary` сверяет метрики повтора с тем, что записал оригинал. Повтор с добавленной метрикой — не повтор, а новое намерение, и раньше он отдавал 200, теряя метрику навсегда. Теперь 409 с перечнем `category_id` (текст из одних id).
- Ветка `except IntegrityError` в `app/api/daily_summary.py` покрыта тестом: первый lookup «ослеплён» (ровно то, что видит проигравший гонку), запись натыкается на уникальный ключ, роутер перечитывает и отдаёт 200 результатом победителя.
- `frontend/lib/api.ts` — **mod**: `idempotencyKey` у `apply()` стал обязательным. Забыть его было бесшумно: вызов проходит, день молча удваивается.
- `app/schemas/daily_summary.py` — **mod**: `existing_entry_id` убран из apply-DTO. `JournalOp` — контракт apply (сервер поле не читал), `JournalOpPreview` — контракт draft. Apply-DTO переведён на `extra="ignore"`, чтобы клиент, возвращающий полученный объект целиком, не получал 422; LLM-facing схемы остались на `extra="forbid"`.
- `tests/test_daily_summary.py` — **mod**: `DAY_TEXT`/`MORNING_TEXT` подняты в шапку модуля, до `_plan_json`, который их использует.
- `app/api/daily_summary.py` — **mod**: в докстринге `apply_plan` записано, что откат делает `apply_daily_summary` (в отличие от `app/api/entries.py`, где `rollback()` в роутере) — чтобы следующая правка не добавила второй.

Feedback loops: pytest 229/229 green, `ruff check` clean, `ruff format --check` clean, `mypy --strict app` clean (51 файл); frontend — `tsc --noEmit` clean, `eslint` clean, `bun test` 474/474 green.

## 2026-07-30 — PHASE-01/74 раунд 3: правки по ревью

Второй заход завернули на асимметрии идемпотентности и дублировании правила о режимах журнала. Поведение изменилось только в сторону отказа: то, что раньше молча отвечало 200 и теряло написанное, теперь отвечает 409.

**Идемпотентность стала симметричной.** `app/crud/daily_summary.py` — **mod**: `find_applied_summary` сверяет с квитанцией не только метрики.

- Другая дата под тем же ключом -> 409 (`this Idempotency-Key already applied another date; use a new key`). Проверка идёт до сверки метрик: ключи записей строятся из ключа и `category_id`, дата в них не участвует, поэтому «тот же ключ, следующий день» до этого выглядел безупречным повтором и второй день не записывался никогда.
- Журнал там, где оригинал его не писал (`request.journal is not None`, `row.journal_entry_id is None`) -> 409. Зеркало случая с добавленной метрикой; текст дня в сообщение не попадает, оно строится из одних фактов.
- `tests/test_daily_summary.py` — **mod**: `test_a_key_reused_with_an_added_journal_is_a_conflict` (записей журнала за дату по-прежнему нет), `test_a_key_reused_for_another_date_is_a_conflict` (на вторую дату не записано ничего).

**409 из ветки гонки больше не 500.** `app/api/daily_summary.py` — **mod**: повторный `find_applied_summary` внутри `except IntegrityError` обёрнут своим `try/except DailySummaryApplyError` — соседний обработчик к этому моменту уже пройден, и отказ перечитывания уходил наружу как 500. `tests/test_daily_summary.py` — **mod**: `test_a_lost_race_with_an_extra_metric_answers_409_not_500` — проигравший гонку с расширенным набором метрик получает 409.

**Правило о режимах живёт в одном месте.** `app/crud/daily_summary.py` — **mod**: `resolve_journal_mode` и предварительный `journal_crud.get_day_journal_entry` удалены, `op_journal.mode` уходит в `write_day_journal` как есть. Правило «`create` на непустом дне = `append`» там уже реализовано, так что копия наверху стоила лишнего round-trip к БД и второго места, где её пришлось бы править.

- `tests/test_journal.py` — **mod**: `TestWriteDayJournal` — режимы проверяются на своём уровне (create на непустом дне дописывает, append, replace, append на пустом дне создаёт, mood/tags заполняются только пустые).
- `tests/test_daily_summary.py` — **mod**: четыре API-теста режимов заменены одним `test_the_requested_mode_reaches_the_journal_layer` — с уровня apply проверяется только то, что режим доходит до журнала.

**Вторая линия обороны на фронте.** `frontend/hooks/useDailySummary.ts` — **mod**: `setEntryDate` при смене даты выпускает новый `applyKey` — смена дня это новая попытка. Проверка на бэкенде обязательна и остаётся: ключ приходит с клиента, а клиент может быть любым. `hooks/useDailySummary.test.ts` — **mod**: смена даты меняет ключ и дату в вызове apply.

Feedback loops: pytest 234/234 green, `ruff check` clean, `ruff format --check` clean, `mypy --strict app` clean (51 файл); frontend — `tsc --noEmit` clean, `eslint` clean, `bun test` 475/475 green.

## 2026-07-30 — PHASE-01/75: разбор дня ставит галки в чек-листах

Третий срез фичи. Пересказ дня теперь может отметить пункт чек-листа — витамины, привычки, что угодно boolean. Опасность среза не в объёме, а в том, что `PUT /entries/checklist` принимает **полную карту** `{field_id: bool}`: план, которому дали её заполнять, снял бы утреннюю галку за то, что про витамины не было сказано ни слова. Молчание — «не сказал», а не «не сделал».

**Снять галку невозможно, и это свойство схемы, а не промпта.** `app/schemas/daily_summary.py` — **mod**: `CheckOp` без поля `value` вообще, `extra="forbid"`. Значения `false` в плане не существует как слова, поэтому его нельзя сказать ни при какой формулировке промпта. `checklist: list[CheckOp]` добавлен в `DailySummaryPlan`, `DailySummaryDraftResponse` и `DailySummaryApplyRequest`; `_must_write_something` теперь считает пустым запрос без всех трёх частей — день из одних галок применяется наравне с остальными.

**Слияние на сервере, чистой функцией.** `app/crud/daily_summary.py` — **mod**: `merge_checklist_marks(current, marked_field_ids)` берёт текущее состояние дня за базу и умеет только поднимать значения — результат отличается от `current` в одну сторону. Тестируется отдельно, потому что именно здесь была бы потеря данных. `validate_check_ops` / `_validate_one_check` повторяют три проверки ручки чек-листа в том же порядке (категория существует, её `display_mode` — `checklist`, поле её собственное и boolean), сообщения из одних id. `_checks_by_category` группирует отметки по категории: две галки одной категории обязаны встретиться в одной карте до записи, иначе вторая запись строилась бы на состоянии, прочитанном до первой.

**Одна транзакция на весь день.** `app/crud/entry.py` — **mod**: `upsert_checklist_entry` разделён на `upsert_checklist_values` (без коммита, транзакцией владеет вызывающий) и тонкую обёртку с коммитом для ручки. Добавлен `get_checklist_state` — состояние галок за дату, **только boolean-поля**: карта из этого чтения уходит обратно в запись как "true"/"false", и попади в неё числовое поле, разбор дня переписал бы 30 отжиманий в "false". Текущее состояние читает бэкенд внутри транзакции, а не клиент: предпросмотр мог висеть открытым час, пока галку ставили руками на Today.

**Отказ — 422, как у ручки.** Небулево поле или поле не-checklist категории отвергается 422 (а не 400, как метрики): ровно этим статусом `PUT /entries/checklist` уже отвечает на ту же ошибку, и через разбор дня она не становится другой ошибкой.

Тронутые файлы:

- `app/schemas/daily_summary.py` — **mod**: `CheckOp`, `checklist` в трёх DTO, обновлённый `_must_write_something`.
- `app/crud/daily_summary.py` — **mod**: `validate_check_ops`, `merge_checklist_marks`, `_checks_by_category`, применение отметок внутри общей транзакции, дедуп `entry_ids`.
- `app/crud/entry.py` — **mod**: `get_checklist_state`, `upsert_checklist_values` (без коммита), константы `CHECKED_VALUE`/`UNCHECKED_VALUE`.
- `app/llm/daily_summary.py` — **mod**: `build_checklist_catalog` (отдельный каталог: числовое поле спрашивает «сколько», галка — «делал ли»), блок `checklist` в схеме ответа промпта, правило «галку только ставят», валидация плана через `validate_check_ops`.
- `app/api/daily_summary.py` — **mod**: `checklist` прокинут в draft-ответ.
- `tests/test_daily_summary_checklist.py` — **new**: схема (галку нельзя снять, `value` в `CheckOp` нет), валидация, чистое слияние, API (упомянутое ставится, отмеченное руками переживает пересказ без него, план без чек-листа не трогает день, 422, откат отметок при отвергнутой метрике, повтор по ключу ничего не переписывает).

Frontend:

- `lib/api.ts` — **mod**: тип `CheckOp`, необязательный `checklist` в `DailySummaryPlan` (фронт впереди бэкенда читает старый draft как «галок нет»), `apply()` принимает `checklist` третьим аргументом.
- `hooks/useDailySummary.ts` — **mod**: `checklist`/`checkStates`/`toggleCheck`, `checkCheckboxLabel`, `CHECKLIST_TITLE`; `enabledCount` считает метрики и галки вместе; `resolveLabel` принимает `OpTarget` (пара id), а не только метрику.
- `app/daily-summary/page.tsx`, `app/m/daily-summary/page.tsx` — **mod**: секция отметок с чекбоксами и названием категории на каждой строке — «B12» само по себе не говорит, какой чек-лист меняется.
- `hooks/useDailySummary.test.ts`, `app/daily-summary/page.test.tsx`, `app/m/daily-summary/page.test.tsx` — **mod**: покрытие секции + сдвиг позиционных аргументов `apply` в существующих проверках.

Feedback loops: pytest 260/260 green, `ruff check` clean, `ruff format --check` clean, `mypy --strict app` clean (51 файл); frontend — `tsc --noEmit` clean, `eslint` clean, `bun test` 494/494 green.

## 2026-07-30 — PHASE-01/75 раунд 3: правки по ревью

Ревью завернуло срез на трёх дублированиях одного правила и одной дыре в гварде идемпотентности. Поведение изменилось в двух местах: чтение галок перестало смешивать записи за дату, а повтор ключа с метрикой в переиспользованную запись теперь 409 вместо 200.

**«Какая запись и есть день» — одно правило на всех.** `app/crud/entry.py` — **mod**: `_checklist_entry_id(db, category_id, entry_date)` — минимальный `id` среди записей за дату. Раньше тот же `order_by(Entry.id).limit(1)` стоял тремя копиями: в `upsert_checklist_values`, в `_entry_for_metrics` и (неявно, через join по дате) в `get_checklist_state`.

- `get_checklist_state` читает `EntryValue` **только** этой записи, а не всех строк за дату. Посторонняя запись той же категории за ту же дату (из формы или доставшаяся от времён до инварианта) содержит своё значение того же поля, и результат чтения зависел от порядка строк в выдаче: галка, стоящая в записи дня, могла прочитаться как снятая — и тут же быть записана обратно как `false`.
- `upsert_checklist_values` и `app/crud/daily_summary.py::_entry_for_metrics` резолвят запись тем же вызовом.
- `tests/test_daily_summary_checklist.py` — **mod**: `test_a_stray_entry_cannot_untick_the_day` — галка стоит в записи с меньшим id, посторонняя запись несёт `"false"` того же поля; apply, не упоминающий это поле, обязан оставить галку. Проверено падающим до правки (`assert {b12: False, d3: True} == {b12: True, d3: True}`).

**Квитанция помнит, что записала.** Отступление от «Schema: без изменений» — второе в этой фиче и вынужденное. `_assert_metrics_already_written` выводил «что записал ключ» из содержимого записей, перечисленных в квитанции. Для checklist-категории эта запись переиспользуется, и значение, набранное руками **до** apply, было неотличимо от записанного этим ключом: повтор с новой метрикой в такое поле выглядел точным повтором и отвечал 200, не записав ничего и никогда уже не сумев записать.

- `app/models/applied_daily_summary.py` — **mod**: колонка `metric_pairs` — явный список пар `(category_id, field_id)`, записанных этим ключом. Пересчитать её задним числом нельзя, поэтому она собирается по ходу apply.
- `alembic/versions/2026_07_30_2200-f6b8c0d2e4a7_applied_daily_summaries_metric_pairs.py` — **new**: обратимая миграция; `upgrade`/`downgrade`/`upgrade` прогнаны на чистой БД. Квитанции старше колонки получают `[]` — повтор такого ключа с метриками отвечает 409. Направление выбрано осознанно: «возьмите новый ключ» дешевле молча потерянной метрики.
- `app/crud/daily_summary.py` — **mod**: `_assert_metrics_already_written` стал синхронным (к БД ходить незачем) и сверяет повтор с `row.metric_pairs`; докстринг переписан под новый источник доказательств.
- `tests/test_daily_summary_checklist.py` — **mod**: `test_a_key_reused_with_a_metric_into_a_prefilled_field_is_a_conflict` — число проставлено руками до apply, ключ пишет только галки, повтор с метрикой в это поле обязан дать 409. Проверено падающим до правки (`assert 200 == 409`).

**Продуктовое решение зафиксировано ADR.** `docs/PHASE-01/ADRs/done/ADR-0007-checklist-day-entry-reuse.md` — **new**: почему метрика в checklist-категорию пишется в запись дня, а не в новую (инвариант «одна запись дня» против «каждый apply — новая запись»), и почему из этого следует изменение контракта идемпотентности метрик (#39): переиспользованная запись не является доказательством авторства значения.

**N+1 в гварде галок свёрнут.** `app/crud/daily_summary.py` — **mod**: `_ticked_boxes` — один запрос вместо вызова `get_checklist_state` в цикле по категориям (`Entry.id.in_(<подзапрос min(id) по категориям>)`, фильтр по boolean-типу и `value = 'true'`). Подзапрос выбирает ту же строку, что `_checklist_entry_id`: `min(id)` — это `order_by(id).limit(1)`, сказанное множественно.

**Недостающий откат покрыт.** `tests/test_daily_summary_checklist.py` — **mod**: `test_a_rejected_tick_takes_a_written_metric_back_out` — цикл метрик выполняется раньше `_checks_by_category`, поэтому к моменту отказа по галке числа уже во flush. Обратное направление (отвергнутая метрика откатывает галки) было покрыто, это — нет.

**Докстринг `_validate_one_check` приведён к фактам.** Утверждение «те же три проверки, что делает `PUT /entries/checklist`, в том же порядке» не соответствовало `app/api/entries.py`: ручка проверяет только `display_mode` и отвечает 404 на неизвестную категорию. Теперь в докстринге записано, что общая — одна проверка из трёх, и почему план строже (ids приходят от модели, а не из UI, который умеет предложить только реальные галки) и почему 422 вместо 404.

**Одна константа `CHECKLIST_DISPLAY_MODE`.** `app/api/entries.py`, `app/llm/onboarding.py` — **mod**: свои литералы удалены, обе импортируют объявление из `app/crud/category.py` (как уже делали `app/api/categories.py`, `app/crud/daily_summary.py`, `app/llm/daily_summary.py`).

**TODO без issue reference закрыт.** `frontend/lib/api.ts` — **mod**: комментарий про необязательные `checklist?`/`journal?` в `DailySummaryPlan` ссылается на заведённый `issues/PHASE-01/backlog/83-daily-summary-plan-fields-required.md` (#83) — снять `?` после выкатки, в которой бэкенд и фронтенд уходят вместе.

Тронутые файлы:

- `app/crud/entry.py` — **mod**: `_checklist_entry_id`, переписанные `get_checklist_state` и `upsert_checklist_values`.
- `app/crud/daily_summary.py` — **mod**: `_ticked_boxes`, синхронный `_assert_metrics_already_written` на `metric_pairs`, `_entry_for_metrics` через общий хелпер, сбор `metric_pairs` в apply, докстринг `_validate_one_check`.
- `app/models/applied_daily_summary.py` — **mod**: колонка `metric_pairs`.
- `alembic/versions/2026_07_30_2200-f6b8c0d2e4a7_applied_daily_summaries_metric_pairs.py` — **new**.
- `app/api/entries.py`, `app/llm/onboarding.py` — **mod**: импорт общей константы.
- `tests/test_daily_summary_checklist.py` — **mod**: три новых теста (посторонняя запись, откат метрики по отвергнутой галке, повтор с метрикой в предзаполненное поле).
- `docs/PHASE-01/ADRs/done/ADR-0007-checklist-day-entry-reuse.md` — **new**.
- `issues/PHASE-01/backlog/83-daily-summary-plan-fields-required.md` — **new**.
- `frontend/lib/api.ts` — **mod**: комментарий со ссылкой на #83.

Feedback loops: pytest 263/263 green, `ruff check` clean, `ruff format --check` clean, `mypy --strict app` clean (51 файл); миграция прогнана `upgrade`/`downgrade`/`upgrade`; frontend — `tsc --noEmit` clean, `eslint` clean, `bun test` 494/494 green.

## 2026-08-02 — PHASE-01/84 голосовой ввод дня: оценка питания по описанию

Дата 2026-08-02. Единственное изменение бэкенда в этом тикете — разрешить модели выводить числа питания из описания еды. До сих пор промпт разбора дня запрещал это буквально: `Do not infer a number nobody stated`. Правило оставлено на месте и сужено по имени, а не удалено, потому что оно правильное везде, кроме одного случая.

Случай такой. «Отжался 30 раз» несёт своё число само. «Съел борщ и котлету» — законченное утверждение о дне, в котором числа нет вообще, и раньше оно уходило в `unresolved`, то есть не записывалось никуда. Разница между едой и остальным не в снисходительности к модели: у порции борща калорийность знаема, у неуточнённой пробежки длина — нет. Ровно эта формулировка и стоит в промпте.

Оценка помечается флагом `estimated` на операции метрики. Это не тот же сорт сомнения, что `uncertain`: тот про то, *куда* попадёт число, а оценка может быть уверенно положена в Питание · Калории и всё равно оставаться догадкой о размере порции. Поэтому оценочная строка приходит в предпросмотр **включённой** — категорию выбрали слова самого пользователя, открыт только порядок величины, — но подписанной. Заставлять отмечать четыре галочки на каждый приём пищи значит вернуть ровно то трение, ради снятия которого фича и делается.

За чекбоксом флаг перестаёт значить что-либо: apply пишет одобренную оценку как обычное число. Хранить сомнение рядом со значением рассматривалось и отброшено — пользователь уже ответил на этот вопрос, поставив галочку, а дневник, который помнит, какие из его чисел были догадками, не умеет их складывать.

Тронутые файлы:

- `app/schemas/daily_summary.py` — **mod**: поле `estimated: bool = False` на `LogMetricOp`.
- `app/llm/daily_summary.py` — **mod**: `estimated` в форме JSON и четыре правила питания в промпте (исключение, оценка блюда целиком одним `source_text`, обычная порция против названной, запрет ставить флаг вне полей питания).
- `tests/test_daily_summary_nutrition.py` — **new**: 9 тестов — дефолт флага, парсинг, правила промпта (включая то, что старое правило не удалено), проброс через draft, запись оценки через apply.

Feedback loops: pytest 310/310 green, `ruff check` clean, `ruff format --check` clean, `mypy --strict app` clean (58 файлов). Миграций нет.

## 2026-08-10 — PHASE-01/73 перестановка полей категории (раунд 2, бэкенд-половина)

Дата 2026-08-10. Тикет фронтендовый, но ревью нашло в нём дыру ровно на границе: перестановка полей меняет только `Field.order`. Id сохраняются, строки в таблице не двигаются, `selectinload` возвращает их в порядке, который никто не обещал — и клиент получал ту же последовательность, что до перестановки. То есть сохранение проходило, а выглядело как отказ.

Правка одна: `Category.fields` объявлен с `order_by="(Field.order, Field.id)"`. Порядок полей становится частью контракта ответа, а не свойством того, как строки легли в таблицу. Тай-брейк по `id` нужен не для красоты: поля, созданные одним батчем (в том числе через `POST /categories` с готовым списком), делят один `order`, и без второго ключа сортировка не тотальна.

Миграции нет и быть не может — `order_by` живёт в ORM, схема не меняется.

Тронутые файлы: 2 (0 new, 2 mod).

- `app/models/category.py` — **mod**: `order_by` на relationship `fields`.
- `tests/test_categories.py` — **mod**: `test_reordered_fields_come_back_in_the_new_order` — красный до правки (`assert [1, 2] == [2, 1]`). Проверяет три ответа, а не один: тело PATCH, отдельный GET категории (порядок должен пережить рефетч, а не быть эхом порядка элементов в запросе) и список категорий, которым питается Today.

Feedback loops: pytest 311/311 green, `ruff check` clean, `ruff format --check` clean, `mypy app` clean (58 файлов). Прогон против временного постгреса на порту 5434 — штатный 5433 занят контейнером другого проекта.

## 2026-08-10 — PHASE-01/73 hero-карточка дашборда (серверная половина)

Дата 2026-08-10, тикет `73-dashboard-hero-today-ring`. Дашборду нужна последняя *сохранённая* запись, а `GET /entries` умел только `entry_date desc`: чтобы найти одну строку, клиент тянул всю выдачу и сортировал сам.

Добавлен параметр `sort` с двумя значениями. `entry_date_desc` — прежнее поведение и значение по умолчанию, поэтому ни один существующий вызов не поменял выдачу. `created_at_desc` отвечает на другой вопрос — «что записано последним» — и с `limit=1` отдаёт ровно одну строку. Направление зашито в значение: возрастающий порядок ни одному экрану не нужен, а отдельный `order` завёл бы четыре комбинации из двух осмысленных.

Вторичный ключ `id desc` при сортировке по времени записи не косметика: `created_at` ставится с точностью базы, и две записи одной секунды иначе возвращались бы в произвольном порядке — «последняя запись» на дашборде прыгала бы между ними от запроса к запросу.

Тронутые файлы: 5 (0 new, 5 mod).

- `app/schemas/entry.py` — **mod**: `EntrySort(str, Enum)` — словарь порядков эндпоинта.
- `app/schemas/__init__.py` — **mod**: реэкспорт `EntrySort`.
- `app/crud/entry.py` — **mod**: `get_entries(..., sort=...)`; `order_by` выбирается по значению, `offset/limit` применяются после него.
- `app/api/entries.py` — **mod**: query-параметр `sort` с дефолтом; неизвестное значение отбивается валидацией FastAPI (422), а не молчаливым фолбэком.
- `tests/test_entries.py` — **mod**: `TestEntrySort` — записи создаются в обратном порядке к их датам, иначе оба порядка дали бы одну и ту же выдачу и тест прошёл бы, не переключив сортировку.

Feedback loops: pytest 315/315 green, `ruff check` clean, `ruff format --check` clean, `mypy app` clean (58 файлов). Миграций нет. Прогон против постгреса на порту 5434.

## 2026-08-30 — PHASE-03/106 периметр API: CORS-allowlist и запрет пустого ключа в проде

Дата 2026-08-30, тикет `106-tighten-api-perimeter-for-inbox`. Два удобных в разработке значения — пустой `API_KEY` и `allow_origins=["*"]` — были зашиты так, что в проде их держала только дисциплина. Теперь их держит отказ стартовать: `ENVIRONMENT=prod` плюс пустой ключ или `*` в `CORS_ORIGINS` роняет сборку настроек с сообщением, называющим переменную, до первого запроса.

Приложение собирается функцией `create_app(config)`, а не на импорте: список origin'ов и наличие схемы API зависят от настроек, и тест обязан уметь поднять приложение с другим `Settings`, не подменяя глобальный объект. Точка входа `app.main:app` не изменилась.

Сравнение ключей переехало в bytes. Это не косметика: `secrets.compare_digest` кидает TypeError на не-ASCII `str`, Starlette декодирует заголовки как latin-1 — и заголовок с кириллицей отдавал 500 вместо 401, то есть неаутентифицированный вызывающий отличал кривой ключ от неверного по коду ответа.

Warning про выключенную auth переехал на старт (`warn_if_auth_disabled`, once-семантика). Строка, повторяющаяся на каждый запрос, перестаёт читаться через минуту dev-сессии.

`/docs`, `/redoc` и `openapi.json` в проде выключены целиком: Swagger UI грузится браузером и заголовок `X-API-Key` послать не может, так что «закрыть ключом» для него не работает. Решение записано в `deploy/README.md`.

Тронутые файлы: 7 (1 new, 6 mod), из них 2 вне сервиса.

- `app/core/config.py` — **mod**: `ENVIRONMENT`, `CORS_ORIGINS: list[str]`, `PerimeterError`, `docs_enabled`, валидатор `_enforce_prod_perimeter`; источники env/dotenv подменены на читающие списки как `a,b,c` (JSON в compose-файле — источник ошибок).
- `app/core/auth.py` — **mod**: сравнение в bytes, `warn_if_auth_disabled()`, из `require_api_key` убран per-request warning.
- `app/main.py` — **mod**: `create_app(config)`, CORS из настроек, docs по `config.docs_enabled`, вызов `warn_if_auth_disabled()` на старте.
- `tests/test_perimeter.py` — **new**: 14 тестов, ни один не трогает базу — периметр проверяется до того, как запрос дойдёт до ручки, и тест периметра, которому нужен постгрес, перестаёт запускаться.
- `tests/test_auth.py` — **mod**: `test_empty_api_key_env_disables_auth` — единственный тест, описывавший старое поведение (warning на каждый запрос); теперь требует тишины.
- `deploy/docker-compose.prod.yml` — **mod**: `ENVIRONMENT: prod`, `CORS_ORIGINS: ${CORS_ORIGINS:-}`.
- `deploy/README.md` — **mod**: раздел «Периметр», решение по `/docs`, проверка acceptance курлом вместо Swagger.

Feedback loops: pytest 329/329 green, `ruff check` clean, `ruff format --check` clean, `mypy --strict app` clean (58 файлов). Миграций нет, голова Alembic прежняя — `a7c9e1b3d5f8`. Docker-демон на машине не поднят, поэтому штатный `make check` не отработал бы целиком: прогон шёл против постгреса на 5432 с той же базой `habit_tracker_test`.

## 2026-08-30 — PHASE-03/107 одна граница суток: `local_date()` как единственный ответ

Дата 2026-08-30, тикет `107-single-day-boundary`. Девять тикетов фазы приписывают данные дню, и до этой правки в проекте было два разных ответа на вопрос «которому дню принадлежит момент»: час старта суток у одних, календарная дата по Берлину у других. Отметка в 00:30 попала бы в разные дни на одном экране. Теперь ответ один — `app/core/daytime.local_date(at)`, день идёт от `DAY_START_HOUR` местных часов до того же часа следующей даты.

Функции не принимают ни пояс, ни час старта параметрами, и это не забывчивость: `#86` переносит источник настроек в версионированный `day_rule_set`, и параметр превратил бы перенос в правку всех вызовов. Сигнатура закреплена тестом, а не только комментарием.

Наивный `datetime` отвергается `ValueError` вместо молчаливого чтения как UTC — этот дефект модуль и заведён предотвращать. `APP_TIMEZONE` проверяется при сборке настроек, поэтому опечатка роняет старт процесса, а не первый запрос.

Переходы на летнее и зимнее время покрыты не примерами, а свойством: тест проходит обе даты поминутно и требует, чтобы `local_date` и `day_bounds` совпадали на каждом моменте. Здесь же вскрылась неточность в тексте тикета: 23-часовые сутки при границе 04:00 — это **2026-03-28**, а не 2026-03-29, потому что перевод в 02:00 попадает в предыдущий логический день. Тест написан по правилу, а не по тексту.

Тронутые файлы: 6 (3 new, 3 mod), из них 1 вне сервиса.

- `app/core/daytime.py` — **new**: `local_date(at)`, `today_local()`, `day_bounds(d)`; ни базы, ни FastAPI, ни сети.
- `app/core/config.py` — **mod**: `APP_TIMEZONE`, `DAY_START_HOUR` (`ge=0, le=23`), валидатор `_timezone_must_resolve` — временный источник правила до `#86`.
- `app/llm/context.py` — **mod**: `date.today()` → `today_local()`; период инсайтов кончался календарной датой сервера, а не днём пользователя.
- `app/crud/streak.py` — **mod**: только докстринг. UTC-сутки остались (Out of Scope тикета), но перестали называться «конвенцией всего продукта» и помечены `TODO(#90)`.
- `tests/test_daytime.py` — **new**: 22 теста, базы не трогают; граница с двух сторон, полночь, оба перевода часов поминутно, отказ на наивном `datetime`, тесты на сигнатуры.
- `habit-tracker/docs/day-boundary.md` — **new**: правило, таблица моментов, что вызывать, что переносит `#86`, единственное известное расхождение.

Feedback loops: pytest 351/351 green, `ruff check` clean, `ruff format --check` clean (80 файлов), `mypy --strict app` clean (59 файлов), `alembic heads` — одна голова `a7c9e1b3d5f8`. Миграций нет: схема не менялась. Docker-демон на машине не поднят, поэтому `make check` целиком не отработал бы — прогон шёл против постгреса на 5432, база `habit_tracker_test`. Фронтенд не менялся: у тикета нет UI-слоя.

## 2026-08-30 — PHASE-03/86 день существует: `day_rule_set`, `day`, `GET /day/{date}` и страница дня

Дата 2026-08-30, тикет `86-day-exists-rule-set-and-day-page`. Первый срез вводит сам предмет: день как строку в базе и канон дня как версионированную строку рядом. Канон менялся дважды за месяц; будь потолок часов константой в модуле, следующая правка переписала бы вердикты всего прошлого и объяснить, почему 14 августа считалось иначе, было бы нечем.

Пересечение интервалов правил отвергает база (`EXCLUDE USING gist (daterange(valid_from, valid_to, '[)') WITH &&)`), а не сервис: проверку в сервисе обходит любой писатель, который через него не идёт — импорт, следующая миграция, сессия `psql`. Интервал полуоткрытый, поэтому смена канона — одна дата, а не пара, которую надо держать согласованной.

`kind` и `is_nocode` материализуются при создании дня. Выводить их на чтении означало бы переписать каждый прошлый вторник при следующей правке расписания недели — ровно то, что версионированный канон и заведён предотвращать.

Источник границы суток переехал с настроек на таблицу, **сигнатура `local_date(at)` не менялась**: `app/crud/day.py` публикует `DayBoundary` действующего правила вызовом `daytime.use_boundary()`, потребители не тронуты. Запасной источник (настройки) остаётся для процесса, который до дня ещё не дошёл; его значения по умолчанию равны сидовой строке.

Ручка отвечает «плана нет» явно (`plan: null`, `has_plan: false`), а не 404: пустой день — ответ, и 404 не дал бы читателю отличить пустой день от неверного URL. 404 остался за датой, которую не покрывает ни одно записанное правило.

Тронутых файлов: 21 (13 new, 8 mod) в бэкенде и фронтенде, плюс 22 тестовых файла фронтенда, куда добавлен `dayAPI` в мок `@/lib/api` (bun фиксирует имена экспортов модуля при первой линковке, поэтому частичный мок удалил бы член у следующего сьюта).

- `app/models/day.py` — **new**: `DayRuleSet` (интервал + GiST-исключение) и `Day` (PK — дата, `kind`/`is_nocode` заморожены при создании, `opened_at` NULL пока день не открывали).
- `app/day/rules.py` — **new**: чистая логика канона — `covers`, `resolve_rule`, `active_rule`, `day_kind`, `is_nocode_date`, `SEED_RULES`. Базы не трогает.
- `app/day/__init__.py` — **new**: пакет дня.
- `app/crud/day.py` — **new**: `list_rules`, `seed_rules`, `rule_for_date`, `get_day`, `ensure_day`, `publish_boundary`, `refresh_day_boundary`. Таблица правил читается целиком: правило «действует на» написано один раз, в Python, а не второй раз в SQL.
- `app/schemas/day.py` — **new**: `DayResponse`, `DayRuleSetResponse`, `DayDetailResponse`.
- `app/api/day.py` — **new**: `GET /api/v1/day` (сегодня по границе суток) и `GET /api/v1/day/{date}`.
- `alembic/versions/2026_08_30_1200-c8e0a2b4d6f9_day_and_rule_set.py` — **new**: обе таблицы, исключающее ограничение и сид двух правил; `downgrade()` проверен на живой базе.
- `app/core/daytime.py` — **mod**: `DayBoundary`, `use_boundary`, `reset_boundary`, `current_boundary`; `local_date`/`day_bounds` читают опубликованную границу. Сигнатуры не менялись.
- `app/main.py` — **mod**: роутер дня в `API_ROUTERS`, `_publish_day_boundary()` на старте.
- `app/models/__init__.py`, `app/schemas/__init__.py` — **mod**: реэкспорт.
- `tests/conftest.py` — **mod**: autouse-фикстура сбрасывает опубликованную границу между тестами — она процессная по замыслу, и вставленное одним тестом правило иначе решало бы, какой сегодня день, для всех следующих.
- `tests/test_day_rules.py` — **new**: 26 тестов; полуоткрытый интервал с двух сторон, резолвер, отказ базы на пересечении, идемпотентный сид, публикация границы, grep-проверка «`def local_date` в репозитории ровно один».
- `tests/test_day.py` — **new**: 11 тестов ручки; вид дня, legacy-правило на 14 августа, `opened_at = null`, «плана нет» вместо 404, `X-API-Key`, неизменность `kind` после новой строки расписания.
- Фронтенд — **new**: `lib/day-format.ts` (+тест), `hooks/useDay.ts` (+тест), `components/DayScreen.tsx` (+тест), `components/mobile/MobileDayScreen.tsx`, страницы `app/day/page.tsx`, `app/day/[date]/page.tsx`, `app/m/day/page.tsx`, `app/m/day/[date]/page.tsx`; **mod**: `lib/api.ts` (`dayAPI`, типы), `lib/routes.ts` + `lib/routes.test.ts` (экран Day в реестре), `components/route-icons.ts`.
- `habit-tracker/docs/day-boundary.md` — **mod**: раздел «Откуда берётся правило» переписан — источник теперь таблица, настройки стали запасным.

Feedback loops: pytest 386/386 green (было 351), `ruff check` clean, `ruff format --check` clean (88 файлов), `mypy --strict app` clean (65 файлов), `alembic heads` — одна голова `c8e0a2b4d6f9`. Фронтенд: `bun test` 608/608 green (было 574), `bunx tsc --noEmit` clean, `eslint` clean. Docker-демон не поднят, поэтому `make check` целиком не отрабатывал: тесты шли против постгреса на 5432, база `habit_tracker_test`; миграция проверена отдельно на временной базе — `upgrade`, `downgrade`, `upgrade`, плюс сверка схемы после миграции со схемой после `create_all` (колонки, ограничения и индексы совпали).

## 2026-08-30 — PHASE-03/87 план дня доезжает: `plan_section`/`plan_item` и `POST /day/{date}/plan` с валидацией канона

Дата 2026-08-30, тикет `87-plan-sections-items-and-canon-validation`. Главный срез переезда: план становится строками, а ограничения этих строк — перенесённые правила `config.md`. Сегодня «не перезакручивать» и «у задачи обязаны быть окно и критерий» — проза, которую агент либо вспомнил, либо нет; после среза их отклоняет база и API.

Правила разложены по двум местам, и разделение — суть решения. **Построчные — CHECK-ограничения** `plan_item`: у задачи есть окно и критерий, у пункта свободного блока окна нет, задача называет цель квартала или причину, окно идёт вперёд. Они верны для любого писателя — импорта, миграции, сессии `psql`, — потому что мимо них не пишет никто. **Правила документа — сервис** (`app/day/plan_validate.py`): планка `max_work_tasks` из правила дня и «жёсткими бывают только края дня». Оба — свойства плана, а не строки, и триггер на строку сорвал бы импорт исторических дней ([#89]), которые планку нарушали. Сервис дублирует и построчные проверки, но односторонне: база — гарантия, сервис — формулировка, и каждая его ветка покрыта ещё и тестом, который пишет мимо него прямо в таблицу.

Отказ **называет пункт**: `{"error": "too_many_tasks", "item_code": "W5", "message": …}`. «Validation error» отправил бы автора перечитывать документ, который он только что написал, а планка существует ровно потому, что пятая задача — та, что превращает день в переработку. Отказ ничего не удаляет: документ судится до того, как удалена первая строка прежнего плана.

Окно приезжает как `"23:30-00:30"`, а не парой timestamp: и человек, и `/day-open` думают настенными часами, а знание про пояс и границу суток централизовано в `#107`. Время раньше часа границы принадлежит следующей календарной дате, поэтому `23:30-00:30` даёт 60 минут, а не минус двадцать три часа; сохранился и `+24 ч` из `parse_window` для вырожденного случая.

Порядок — позиция в списке, `ord` ставит сервер. Клиентский номер на одну правку отстоит от двух секций с одним `ord`, и база такой план отвергла бы, хотя в редакторе он выглядел целым.

Наложения окон — самосоединение по `&&` поверх GiST-индекса на генерируемой колонке `window`, а не пересчёт на рендере: экран стал потребителем факта, а не его единственным владельцем.

Найдено по ходу: обратное окно до CHECK `ck_plan_item_window_is_forward` не доходит — генерируемая колонка `window` считается раньше, и `tstzrange(23:30, 00:30)` падает сама, ошибкой диапазона. Ограничение на месте и верно, просто не успевает сработать; записано в тесте и в `docs/day-plan.md`.

- `app/models/plan.py` — **new**: `DayPlan` (один план на день, `day_date` unique FK), `PlanSection` (`UNIQUE(plan_id, ord)`), `PlanItem` — четыре CHECK-а, генерируемые `window tstzrange` и `search tsvector`, индексы `(section_id, ord)`, GiST на `window`, GIN на `search`, `(carried_from_item_id)`, частичный `UNIQUE(section_id, code) WHERE code IS NOT NULL`.
- `app/day/plan_validate.py` — **new**: базы не трогает. `PlanRejected` с кодом пункта, `ItemFacts`, `validate_plan`, `check_task_bar`, `check_hard_rigidity`, `check_item_shape`, `parse_window`, `resolve_window`, `to_plain`, `count_tasks`.
- `app/crud/plan.py` — **new**: `prepare_plan` (документ → строки с разрешёнными окнами и `ord` по позиции), `replace_plan`, `get_plan`, `delete_plan`, `find_overlaps` (самосоединение по `&&`), `build_schedule`, `to_response`.
- `app/schemas/plan.py` — **new**: `PlanDocument`/`PlanSectionIn`/`PlanItemIn` на вход, `PlanResponse`/`PlanSectionResponse`/`PlanItemResponse`/`ScheduleEntry`/`ScheduleOverlap`/`PlanRejection` на выход.
- `alembic/versions/2026_08_30_1600-d9f1b3c5e7a0_plan_tables.py` — **new**: три таблицы; `upgrade`/`downgrade`/`upgrade` проверены на живой базе, схема после миграции сверена со схемой после `create_all` — колонки, ограничения и индексы совпали.
- `app/api/day.py` — **mod**: `POST /api/v1/day/{date}/plan` (201, 422 с телом `PlanRejection`); `GET /day` и `GET /day/{date}` отдают план, расписание и наложения.
- `app/schemas/day.py` — **mod**: `DayDetailResponse.plan` теперь `PlanResponse | None`.
- `app/models/__init__.py` — **mod**: реэкспорт `DayPlan`, `PlanSection`, `PlanItem`.
- `tests/test_plan_constraints.py` — **new**: 27 тестов. Половина пишет мимо сервиса прямо в таблицу и требует отказа базы; половина зовёт валидатор без базы.
- `tests/test_plan_post.py` — **new**: 18 тестов ручки — все acceptance-случаи тикета плюс «отклонённый план не трогает прежний» и `X-API-Key`.
- Фронтенд — **new**: `lib/plan.ts` (+тест), `components/day/PlanSections.tsx` (+тест), `components/day/DaySchedule.tsx` (+тест); **mod**: `lib/api.ts` (типы `Plan`/`PlanSection`/`PlanItem`/`ScheduleEntry`/`ScheduleOverlap`/`PlanDocument`, `dayAPI.savePlan`), `components/DayScreen.tsx` + его тест, `components/mobile/MobileDayScreen.tsx`.
- `habit-tracker/docs/day-plan.md` — **new**: форма документа, словарь шести колонок, таблица кодов отказа, где живёт правило на самом деле, наложения.

Тест `DayScreen.test.tsx` «keeps the plan block away once a plan exists» переписан: он задавал `has_plan: true` при `plan: null` — состояние, которого сервер выдать не может, — и держался на том, что экран ветвился по булеву флагу. Экран теперь ветвится по самому плану, а тест рендерит настоящий.

Feedback loops: pytest 431/431 green (было 386), `ruff check` clean, `ruff format --check` clean (94 файла), `mypy --strict app` clean (69 файлов), `alembic heads` — одна голова `d9f1b3c5e7a0`. Фронтенд: `bun test` 633/633 green (было 608), `bunx tsc --noEmit` clean, `eslint` clean. Docker-демон на машине не поднят, поэтому `make check` целиком не отрабатывал: тесты шли против постгреса на 5432, база `habit_tracker_test`.

## 2026-08-30 — PHASE-03/88 отметка трёх состояний с заметкой, блокнот дня и четвёртое «пусто»

Дата 2026-08-30, тикет `88-plan-marks-three-states-and-notebook`. Ради этого весь переезд: отметка перестала висеть на позиции в DOM и перешла на `plan_item.id`. Ключом были `i7`, `t3`, `w1`, поэтому правка одной строки `.md` молча сдвигала соответствие «отметка ↔ пункт», а `.html` с отметками лежал в `.gitignore` — истории отметок не существовало вовсе.

**Четыре «пусто» стали различимы.** `plan_mark` — одна строка на пункт; её отсутствие и есть `pending`. Вместе с `day.opened_at` это отделяет «не открывал» от «открыл и не дошёл», а `state='failed'` от `state='skipped'`. 29 августа — день с нулём отметок — после импорта прочитается как «не открывал», а не как «ничего не сделал». `opened_at` ставит только `GET ...?opened=true` (флаг ставит страница) и отметка с `source='web'`; агент, импорт и cron читают день молча, иначе «не открывал» перестало бы быть устанавливаемым фактом.

**Отметка переживает правку плана.** `POST /plan` заменяет план целиком, поэтому пункт теперь может прислать назад свой `id`: тогда строка сохраняет uuid, а отметка переносится через замену (`snapshot_marks` → `delete_plan` → вставка → `restore_marks`, одна транзакция, `updated_at` отметки не двигается). `id` чужой или отсутствует — новый пункт без отметок; один `id` дважды в документе — 422 `duplicate_item_id` с названным пунктом. Совпадения по тексту нет намеренно: позиционное и текстовое сопоставление и было причиной, по которой отметки терялись.

**Заплатки `plan_server.py` не воспроизведены.** 409 «пустое поверх непустого», подмешивание `localStorage` и перечитывание по `visibilitychange` существовали потому, что запись шла в файл без транзакции. Их место занял `ON CONFLICT (item_id) DO UPDATE`: запрос называет состояние, а не шаг цикла, две вкладки не воскрешают старое значение, побеждает последняя запись, и `updated_at` показывает, какая.

**Цикл — данные, а не if-цепочка**, и записан по обе стороны: `MARK_CYCLE` в `app/day/marks.py` и в `lib/marks.ts`, `пусто → done → failed → пусто`. `skipped` на кольце нет: «стало неактуально» — суждение о плане, а не о работе, и попадать в него четвёртым щелчком человек не должен; в счётчике задач он не считается ни закрытым, ни проваленным.

**`plan_mark_event.item_id` — без внешнего ключа.** Удалённый пункт уносит свою `plan_mark`, и это верно: отметка несуществующей строки не факт ни о чём. Но лог, который забывает, логом не является, поэтому события переживают пункт и читаются по `day_date`.

- `app/models/mark.py` — **new**: `PlanMark` (PK = `item_id`, FK на `plan_item` с CASCADE, CHECK на `state` и `source`), `PlanMarkEvent` (append-only, `from_state`/`to_state` с NULL вместо `pending`, CHECK `from_state IS DISTINCT FROM to_state`, индексы `(item_id, at)` и `(day_date, at)`).
- `app/day/marks.py` — **new**, базы не трогает: `MARK_CYCLE`, `next_state`, `TaskCounts`, `count_tasks`.
- `app/crud/mark.py` — **new**: `day_item` (пункт, но только этого дня), `list_marks`, `set_mark` (upsert + событие в той же транзакции), `snapshot_marks`/`restore_marks` (перенос отметок через замену плана), `task_counts`, `to_response`.
- `app/schemas/mark.py` — **new**: `MarkIn` (словарь состояний проверяется здесь, чтобы опечатка была 422, а не ошибкой ограничения), `MarkResponse`, `TaskCountsResponse`, `NotebookIn`, `NotebookResponse`.
- `alembic/versions/2026_08_30_2000-e0b2d4f6a8c1_plan_marks.py` — **new**: две таблицы; `upgrade`/`downgrade` проверены на временной базе `habit_mig_check`.
- `app/api/day.py` — **mod**: `PUT /day/{date}/marks/{item_id}`, `PUT /day/{date}/notebook`, `?opened=` у обоих `GET`; ответ дня несёт `marks`, `task_counts` и `notebook`.
- `app/crud/day.py` — **mod**: `touch_day`, `get_notebook`, `set_notebook` (через существующий `write_day_journal`, режим `replace`).
- `app/crud/plan.py` — **mod**: `_stored_item_ids`, `_identity`, `prepare_plan(..., keep)`, перенос отметок в `replace_plan`.
- `app/schemas/plan.py` — **mod**: `PlanItemIn.id`; `app/schemas/day.py` — **mod**: `marks`, `task_counts`, `notebook`; `app/models/__init__.py` — **mod**: реэкспорт.
- `tests/test_plan_marks.py` — **new**: 24 теста — цикл, отметка переживает правку текста, четыре «пусто», счётчик со `skipped`, лог событий (включая снятие и переживание удалённого пункта), две вкладки, блокнот одной записью.
- Фронтенд — **new**: `lib/marks.ts` (+тест), `hooks/useDayMarks.ts` (+тест), `components/day/PlanItemMark.tsx` (+тест), `components/day/DayNotebook.tsx` (+тест); **mod**: `lib/api.ts` (типы `Mark`/`MarkState`/`TaskCounts`, `dayAPI.open`/`openToday`/`setMark`/`saveNotebook`), `lib/plan.ts` (`itemKindsById`), `hooks/useDay.ts` (флаг `opened`) + его тест, `components/day/PlanSections.tsx` (необязательный проп `marking`), `components/DayScreen.tsx` + его тест, `components/mobile/MobileDayScreen.tsx`.
- `habit-tracker/docs/day-plan.md` — **mod**: раздел «Отметки» — таблица четырёх «пусто», цикл, лог, правило переноса `id`, открытие дня, блокнот.

Найдено по ходу: `useDayMarks` получает список отметок из ответа дня, и вызывающий обычно строит его выражением `detail?.marks ?? []` — новый массив на каждый рендер. Эффект синхронизации ключуется по строке-сигнатуре содержимого, а не по ссылке: иначе экран уходит в цикл, а хук, который работает только когда вызывающий не забыл `useMemo`, — не хук, а ловушка.

Feedback loops: pytest 455/455 green (было 431), `ruff check` clean, `ruff format --check` clean (99 файлов), `mypy --strict app` clean (73 файла), `alembic heads` — одна голова `e0b2d4f6a8c1`. Фронтенд: `bun test` 664/664 green (было 633), `bunx tsc --noEmit` clean, `eslint` clean. Docker-демон на машине не поднят, поэтому `make check` целиком не отрабатывал: тесты шли против постгреса на 5432, база `habit_tracker_test`; миграция проверена отдельно на временной базе `habit_mig_check` — `upgrade`, `\d` обеих таблиц, `downgrade`.

## 2026-08-30 — PHASE-03/96 бэкап в критическом пути и еженедельный экспорт база → `.md`

Дата 2026-08-30, тикет `96-backup-in-critical-path-and-weekly-md-export`, волна B, первый.
Схемы и миграции нет: тикет операционный, голова Alembic после него та же — `e0b2d4f6a8c1`.

**Бэкап переехал из «желательно» в условие эксплуатации.** С `#88` отметки живут только в
базе, git больше не журнал изменений дня. Старый `backup.sh` при этом молча производил
файл-обманку: `pg_dump | gzip > файл` под `set -e` оставляет усечённый `.gz` с именем
настоящего бэкапа, если дамп умер на середине. Теперь поток пишется в `.partial` и
переименовывается только после трёх проверок — `gzip -t`, пол в 1 КБ на **распакованном**
размере (сжатый ничего не говорит: двести повторов `SELECT 1;` жмутся в 66 байт) и наличие
трейлера `PostgreSQL database dump complete`, которого у обрезанного дампа нет.

**Ротация с полом.** 14 дней по возрасту, но не меньше `MIN_KEEP=3` самых свежих, сколько бы
им ни было лет. Чистая ротация по возрасту опустошает каталог через две недели после того, как
cron молча умер, — ровно тогда, когда дамп нужен.

**Провал виден.** `backup.sh` пишет `backups/backup-status` (`OK` / `FAIL stage=… exit=…`) на
каждом прогоне, возвращает ненулевой код и печатает строку в stderr. `restore-check.sh` этот же
файл читает и отказывается, если там `FAIL` или если свежему дампу больше 36 часов, — то есть
недельная проверка ловит и «дамп не снялся», и «cron вообще не запускался». Мониторинга в
проекте нет намеренно (Out of Scope тикета), так что раз в неделю на лог всё ещё смотрит человек.

**Проверка восстановления автоматизирована, кроме одного шага.** `restore-check.sh` поднимает
одноразовую базу, льёт в неё дамп, печатает `days/plans/items/marks` и падает на пустом,
битом, протухшем и несущем секреты дампе; базу сносит на любом пути выхода. Что в дампе есть
**нужный** день с планом и отметками, один раз проверяет человек по чек-листу README — и это
единственный acceptance-пункт тикета, который остаётся неотмеченным до прогона на VPS.

**Секреты не в дампе — и это проверяется, а не обещается.** `restore-check.sh` гоняет по
распакованному дампу `grep -E` по префиксам реальных кредов (`ya29.`, `1//0`, `sk-ant-`,
`CLAUDE_CODE_OAUTH_TOKEN`, `BEGIN … PRIVATE KEY`, `telethon.session`) и падает на совпадении.
Список задаётся через `if [ -z … ]`, а не через `${VAR:-default}`: первая `}` из `{20}` закрыла
бы подстановку и шаблон молча стал бы `ya29\.[A-Za-z0-9_-]{20` — то есть не совпадал бы никогда.

**Экспортёр «база → `.md`» написан здесь, а не в `#89`.** Тикет разрешал отложить этот слой,
но откладывать было нечего: без него acceptance «экспорт кладёт `.md`-планы за неделю» не
закрывается, а страховка отката (ADR-0014, 1-2 недели) не существует. `#89` теперь пишет только
импортёр и обязан переиспользовать `app/exports/personal_os.py`, а не заводить второй рендер.

**День экспортируется двумя файлами.** План — в `plans/YYYY/MM/YYYY-MM-DD.md`, и он остаётся
планом; что с ним случилось — в `plans/YYYY/MM/YYYY-MM-DD.report.md` (имя, которым те же данные
называл `plan_server.py`). Галочки внутри текста плана пришлось бы вырезать при обратном
импорте ровно из тех строк, по которым импортёр сопоставляет пункты.

- `app/exports/__init__.py` — **new**: пакет рендереров «строки → файл».
- `app/exports/personal_os.py` — **new**: `render_plan` (frontmatter, H1, секции, задачи
  заголовком с подписями, шаги нумерацией, таблица из подряд идущих `table_row`),
  `render_report` (отметки таблицей + блокнот; `None`, когда день не открывали — четвёртое
  «пусто» `#88` переживает экспорт), `export_day`, `export_week`, `week_range`/`week_of`, CLI
  `python -m app.exports.personal_os --out DIR [--week last|current|YYYY-Www]`. Своей
  арифметики дат нет: зона берётся из `current_boundary()` (`#107`). Порядок ключей JSONB
  сортируется — иначе два экспорта одного неизменного дня давали бы разные байты и недельный
  архив нельзя было бы читать диффом.
- `tests/test_export_personal_os.py` — **new**: 11 тестов — план читается как план, окно
  возвращается на настенных часах, жёсткие точки схлопываются в одну таблицу, два экспорта
  байт в байт равны, день без плана не пишет файл плана, отметки и блокнот уезжают в
  `.report.md` и не попадают в текст плана, неделя ложится в папку `2026-W36`, `last` — всегда
  завершившаяся неделя, кривая `--week` отвергается.
- `tests/test_backup_scripts.py` — **new**: 15 тестов, гоняют настоящие `deploy/*.sh` с
  подставными `DUMP_CMD`/`PSQL_CMD` — ни docker, ни постгрес не нужны. Атомарная запись,
  обрезанный дамп, слишком маленький дамп, ротация с полом, четыре отказа `restore-check`
  (нет дампа, протух, битый, ноль дней), секрет внутри дампа, статус-файл `export-md.sh`.
- `deploy/backup.sh` — **mod**: `.partial` + переименование, три проверки, ротация 14 дней с
  полом `MIN_KEEP`, статус-файл, ненулевой код и строка в stderr на каждом отказе.
- `deploy/restore-check.sh` — **new**: пять отказов, одноразовая база, счётчики, `--dump` и
  `--keep-db` для ручной проверки.
- `deploy/export-md.sh` — **new**: недельный прогон экспортёра в `backups/exports/<YYYY-Www>/`,
  статус-файл, вынос ненулевого кода экспортёра наружу.
- `deploy/docker-compose.prod.yml` — **mod**: `BACKUP_DIR:/backups` в backend — без этого
  экспорт ложится в слой контейнера и умирает со следующим `up --build`.
- `deploy/README.md` — **mod**: разделы «Бэкап» (три скрипта, crontab, ротация, как виден
  провал), «Что делать, когда база потеряна» (восемь шагов от дампа до открытой страницы дня),
  «Что бэкап не покрывает» (`gmail_token.json`, `telethon.session`, Keychain агента — и как
  получить каждое заново), «Проверка восстановления руками» с таблицей прогонов.

Найдено по ходу: `MIN_BYTES` на сжатом файле — бесполезная проверка, и первая версия скрипта
её содержала. Поймал тест, а не чтение.

Feedback loops (backend): pytest 481/481 green (было 455), `ruff check` clean,
`ruff format --check` clean (103 файла), `mypy --strict app` clean (75 файлов),
`alembic heads` — одна голова `e0b2d4f6a8c1` (новых ревизий нет), `shellcheck` по трём
скриптам чисто, `bash -n` чисто. Docker-демон на машине не поднят, поэтому `make check`
целиком не отрабатывал: тесты шли против постгреса на 5432, база `habit_tracker_test`.
Фронтенд не тронут — у тикета нет слоя UI, — поэтому `bun test` не гонялся и
`frontend/SESSION_REVIEW.md` не менялся. Ни один скрипт не прогонялся на VPS: docker
недоступен, боевой машины у сессии нет.

## 2026-08-30 — PHASE-03/89: импорт истории personal-os

Тикет: `issues/PHASE-03/done/89-import-personal-os-plans-and-exporter.md`. Тронуто 8 файлов.

- `app/models/import_source.py` — **new**: таблица `import_source` (`kind`, `path` уникальный,
  `sha256`, `imported_at`, `raw`). Файл лежит целиком: разбор лоссовый по построению
  (`<details>`, отметка без строки), и после заморозки personal-os в архив это единственный
  способ вернуться к оригиналу. `sha256` — то, что делает повторный прогон дешёвым и честным.
- `alembic/versions/2026_08_31_0900-f1c3e5a7b9d2_import_source.py` — **new**: одна таблица,
  `down_revision = e0b2d4f6a8c1`. `upgrade`/`downgrade`/`upgrade` проверены на временной базе
  `habit_mig_check89`, `\d import_source` сверен с моделью — имена ограничений совпадают.
- `app/models/__init__.py` — **mod**: реэкспорт `ImportSource`.
- `app/imports/__init__.py` — **new**.
- `app/imports/md_parser.py` — **new**: грамматика `.md` планов (frontmatter, секции, задачи
  `### W1 · …`, подписи `Подпись :: значение`, таблицы, шаги, минимумы, продолжения строк).
  Ничего не судит: канон применяет `app.crud.plan`. Каждый пункт помнит, чем он был на
  странице (`html_form`) — это то, чем отметка находит свою строку.
- `app/imports/plan_state.py` — **new**: чтение блока `<script id="plan-state">` из `.html` и
  отчёта экспортёра из `.report.md`. Ключи разбираются по **странице**, а не по markdown:
  генерируемое расписание сдвигает `t`-нумерацию (на 28.08 — на семь строк), и пересчёт по
  `.md` посадил бы отметки не на те строки. Строки расписания помечаются псевдонимами.
- `app/imports/personal_os.py` — **new**: CLI `python -m app.imports.personal_os --root DIR
  [--dry-run] [--force] [--date]`. Пропуск дня по совпадению `sha256`, сопоставление отметок по
  тексту, заполнение календаря без дыр, `opened_at` только по свидетельству, отчёт с
  предупреждениями. Пишет через `crud.plan.replace_plan` и `crud.mark.set_mark` — второго
  определения плана не заводится.
- `app/exports/personal_os.py` — **mod**: дети задачи пишутся с отступом. Без этого строка под
  `### W1` читается обратно и как шаг задачи, и как следующая строка раздела, и круговой прогон
  на 28.08 менял вложенность.
- `tests/test_import_personal_os.py` — **new**: 30 тестов. Фикстуры
  `tests/fixtures/personal_os/` — живой 28 августа (`.md`, `.html` с настоящими галочками,
  `.report.md` от `plan_server.py`) плюс два маленьких дня под случаи, которых в живых данных
  нет: день без отметок и отметка на строке, которой в `.md` больше нет.
- `tests/test_export_personal_os.py` — **mod**: один assert под новый отступ детей задачи.
- `habit-tracker/docs/day-plan.md` — **mod**: раздел «Импорт истории personal-os».

Найдено по ходу: `plan_server.py:page_labels` считает строки регуляркой `<tr>` без атрибутов и
поэтому пропускает `<tr class="clash">` — на страницах с наложением окон его собственный дамп
отметок съезжает на строку. Браузерный `querySelectorAll("table tbody tr")` их считает; импорт
следует браузеру.

Feedback loops (backend): pytest **511/511 green** (было 481), `ruff check` clean,
`ruff format --check` clean (109 файлов), `mypy --strict app` clean (80 файлов),
`alembic heads` — одна голова `f1c3e5a7b9d2`. Docker-демон не поднят, `make check` целиком не
отрабатывал: тесты шли против постгреса на localhost:5432, база `habit_tracker_test`. Сверх
тестов прогнан живой импорт `~/Documents/MyProj/personal-os` в базу `habit_import_check`
(13 дней, 432 пункта, 22 отметки, 9 дней без плана; второй прогон — нули; `--dry-run` на пустой
базе оставляет её пустой) и круговой прогон экспорт → импорт по всем 13 дням. Фронтенд не
тронут — у тикета нет слоя UI, — `bun test` не гонялся, `frontend/SESSION_REVIEW.md` не менялся.

## 2026-08-30 — PHASE-03/90 и PHASE-03/93: правки по ревью коммита ee5de9d

Один сеанс на два тикета волны: вердикт дня (`#90`) и цели (`#93`). Ревью нашло два блокера,
у которых общий корень — **запись документом там, где приходит часть документа**, — и три
места, где решение существовало только в голове автора.

**Закрытие дня пишет присланные поля, а не весь документ.** `_store_close` собирал `values`
из всех полей `DayCloseIn` и в `on_conflict_do_update` перезаписывал ими каждую колонку. Экран
же шлёт на переопределение вердикта ровно `{verdict_override, verdict_override_note}` — и один
клик обнулял `body_md`, `work_minutes` и три ответа `/day-close`. Теперь пишется
`model_dump(exclude_unset=True)`: не прислали поле — прежнее значение осталось, снятие
переопределения называется вслух (`verdict_override: false`). `source` кладётся только на
вставке.

**День, чей вердикт пришёл прозой, через `POST /close` не закрывается.** Строка с
`source='import'` приходила на экран с `closed: true`, получала блок переопределения — и клик
переводил её в `source='close'`, после чего `recompute_history` пересуживал прожитый август по
отметкам, которых у него нет. Ровно то, что модуль объявляет невозможным. Теперь 409 и текст,
куда идти: `summaries/`.

**Цели квартала обновляются на месте.** `replace_quarter_goals` делал `DELETE FROM quarter_goal
WHERE quarter = :quarter` — а в том же коммите обе колонки `quarter_goal_id` получили FK с
`ondelete='RESTRICT'`. Первая же задача плана, названная целью, ломала `PUT` для квартала
навсегда. Переписано на upsert по `(quarter, ord)` — тем же приёмом, каким это делает
`app.imports.goal_md` и по той же причине: `id` цели — это то, чем прожитый день назвал, ради
чего он был прожит. Позиция, которой в новом наборе нет, снимается, и не снимается, если на неё
ссылается план: 409 с перечислением дней.

**«Все якоря» — это все якоря, вписанные в план.** `anchors_done < anchors_total` читалось как
«закрыты все пять якорей канона», хотя знаменатель берётся из плана и день без единой
строки-якоря даёт 0/0 и выигран. Решение записано в докстринг `app.day.evaluate` вместе с
причиной (якорь существует только как строка markdown до `#92`) и закреплено тестом. Менять
знаменатель на `rule.required_anchors` в этом сеансе не стали — это переоценка всех
импортированных дней августа, отдельный тикет.

Backend:

- `app/crud/summary.py` — **mod**: `_store_close` пишет только присланное; `close_day` отвергает
  `source='import'` через `ImportedDayIsNotClosable`; `_stored_source` читает одну колонку, а не
  сущность (загруженная сущность попадала в identity map, и `recompute_history` судил день по
  копии, прочитанной до записи); докстринги `_to_response` (счётчики — снимок, список якорей —
  живой) и `recompute_history` (переопределение — пятое правило вердикта, одностороннее).
- `app/schemas/summary.py` — **mod**: `DayCloseIn` — «умолчание значит не прислали»; валидатор
  дополнительно запрещает стирать записку переопределения отдельно (иначе пара, запрещённая
  `CHECK`, давала бы 500).
- `app/api/day.py` — **mod**: `POST /day/{date}/close` отвечает 409 на импортированный день.
- `app/crud/goal.py` — **mod**: upsert по `(quarter, ord)`, `QuarterGoalsRejected` (место занято
  дважды, статус не из словаря), `QuarterGoalInUse` (позицию называет план), `_days_pointing_at`.
  Сигнатура сменилась на `list[QuarterGoalIn]` — роутер больше не собирает ORM-объекты.
- `app/api/goals.py` — **mod**: `CONSTRAINT_MESSAGES` + `_constraint_name` — отказ базы называется
  по имени ограничения (`asyncpg` отдаёт `constraint_name` на `__cause__`), неопознанное
  ограничение уходит наверх как 500. Сырой `error.orig` из ответа убран.
- `app/models/checks.py` — **new**: `in_list()` — текст словарного CHECK из того же кортежа,
  который читает код. Переехал из `app/models/summary.py`, чтобы `milestone.status` и
  `quarter_goal.status` не писали свои литералы.
- `app/models/goal.py` — **mod**: CHECK милстона собирается из `MILESTONE_STATUSES`;
  `QUARTER_GOAL_STATUSES` + `ck_quarter_goal_status` — у статуса цели квартала появился словарь.
- `app/models/summary.py` — **mod**: `_in_list` заменён импортом.
- `app/day/evaluate.py` — **mod**: докстринги — что значит «все якоря», почему переработка стоит
  первой (следствие, а не приоритет `config.md`), и что переопределение — пятое правило, живущее
  в `recompute_history`.
- `app/day/rules.py` — **mod**: комментарий про жёсткие края вернулся к `REQUIRED_ANCHORS`.
- `app/day/plan_validate.py` — **mod**: `KIND_ANCHOR` и `KIND_HARD_POINT` дописаны в `__all__`.
- `app/core/daytime.py` — **mod**: утверждение «второй арифметики дней не осталось» сужено до
  факта — `_pin` назван как известное второе выражение.
- `app/imports/goal_md.py` — **mod**: из «Открывается чем» отбрасывается собственный код милстона
  (петля `M5 -> M5`) и коды, которых нет в таблице (сырой `IntegrityError` на FK).
- `alembic/versions/…d5a7c9e1f3b6_quarter_goal_status_check.py` — **new**: `ck_quarter_goal_status`.
  `down_revision = c4f6b8d0e2a5`, голова одна.
- `tests/test_day_close.py` — **mod**: переопределение не стирает прозу, минуты и три ответа;
  снятие переопределения называется вслух; записку нельзя стереть отдельно; импортированный день
  не закрывается и остаётся нетронутым.
- `tests/test_goals.py` — **mod**: `id` целей переживают перезапись при живом плане; позицию,
  названную планом, снять нельзя (409 с датой); неназванная позиция уходит; милстон, которого
  нет, называется своим ограничением; статус вне словаря отвергнут.
- `tests/test_evaluate_day.py` — **mod**: день без единого якоря выигран 0/0 — поведение
  закреплено, чтобы его смена была решением, а не побочным эффектом.

Названные вслух долги, оставленные в этом сеансе:

- `summary_crud.search` реализована с генерируемым `tsvector` и GIN-индексом, но **ручки нет**:
  единственные вызовы — в тестах. `GET /api/v1/day/search?q=` не заведён, потому что путь
  столкнулся бы с `/day/{on}` и требует порядка регистрации; отдельный тикет.
- `recompute_history` на каждом `POST /close` перечитывает всю историю и делает два запроса на
  каждый день с `source='close'`. Оптимизация (пакетное чтение планов и отметок либо пересчёт
  только затронутого дня плюс дешёвая свёртка стрика) — отдельная работа, не тронута.
- `_import_summaries` читает каждый файл дважды и ходит в `_stored_digests` по одному файлу за
  итерацию.
- Три колонки `day_summary` с булевыми именами и целым типом (`wrote_from_scratch`,
  `education_debt`, `reviewed_today`) описаны в модели и в схеме по-разному; переименование —
  миграция плюс правка фронтенда.
- Знаменатель якорей остаётся планом, а не `rule.required_anchors` — до `#92`.

Feedback loops (backend): pytest **585/585 green** (было 575), `ruff check app tests` clean,
`ruff format --check` clean (126 файлов), `mypy --strict app` clean (91 файл), `alembic heads` —
одна голова `d5a7c9e1f3b6`. Docker-демон на машине не отвечает, `make check` целиком не
отрабатывал: тесты шли против постгреса на localhost:5432, база `habit_tracker_test`.
## 2026-08-30 — PHASE-03/108 один планировщик фоновых задач

Фоновая работа получает один процесс. Контейнер `worker` на образе бэкенда с командой
`python -m app.worker`, APScheduler в одном asyncio-цикле, один экземпляр. Системного cron с
прикладной логикой и планирующих `asyncio`-задач внутри gunicorn больше нет ни одного — оба
запрета проверяются тестом, а не чтением кода. Самих заданий тикет не приносит: опрос
источников (`#99`), ретенция (`#104`) и ночной скелет плана (`#151`) регистрируются в том же
реестре своими тикетами.

Тронуто 7 файлов.

- `app/worker.py` — **new**: точка входа `python -m app.worker`. `AsyncIOScheduler`,
  `coalesce=True`, `misfire_grace_time` час, `max_instances=1`. Ждать конца текущего задания
  приходится самому: `AsyncIOExecutor.shutdown` у APScheduler отменяет незавершённые задачи
  независимо от `wait`, поэтому по сигналу планировщик ставится на паузу, `JobRunner`
  досчитывает запущенное и только потом планировщик гасится. Расписание печатается строками на
  старте.
- `app/scheduling/registry.py` — **new**: `ScheduledJob` (имя, интервал, таймаут, функция,
  `summary`, признак `long_running` под будущий запуск `claude` CLI), `JobRegistry` и
  `JobRunner`. Один прогон = `pg_try_advisory_lock` по имени (не взял — пропустил, а не
  поставил в очередь), `asyncio.wait_for` по таймауту, пойманное исключение, записанное
  **классом без текста**: сообщение ошибки — первое место, куда утекает содержимое записи.
- `app/scheduling/__init__.py` — **new**: поверхность пакета. Планировщика здесь нет намеренно —
  пакет, умеющий его поднять, рано или поздно импортируют из веб-воркера.
- `tests/test_scheduler.py` — **new**: 25 тестов. Отдельный процесс проверяет, что импорт
  `app.main` не тянет ни `apscheduler`, ни `app.worker`; grep-инвариант по `git ls-files` ловит
  `crontab`/`cron.d` в коде и планирующую `asyncio`-задачу вне `worker.py`; отдельный тест
  разбирает crontab-врезку `deploy/README.md` и не пускает туда python и docker. Живой
  планировщик гоняется двумя заданиями на интервале 50 мс: падающее остаётся на расписании и не
  мешает соседу. Блокировка проверяется двумя настоящими соединениями (`NullPool`), остановка —
  и внутренним событием, и настоящим `SIGTERM` через `os.kill`.
- `pyproject.toml` — **mod**: `apscheduler>=3.10,<4` в основных зависимостях; override mypy на
  `apscheduler.*` — пакет идёт без `py.typed` и стабов на typeshed не имеет.
- `habit-tracker/docker-compose.yml`, `deploy/docker-compose.prod.yml` — **mod**: сервис
  `worker` (тот же образ, та же БД, портов не публикует, `deploy.replicas: 1`, в проде
  `restart: always`). `container_name` ему не даётся: он конфликтует с `replicas`.
- `deploy/README.md` — **mod**: раздел «Фоновые задания» — таблица всех заданий системы (сходится
  с реестром, расхождение роняет тест), как смотреть логи, как перезапустить, как убедиться, что
  задание идёт, и что пишет второй экземпляр.

Найдено по ходу: тестовая база `habit_tracker_test` общая для параллельных worktree, и таблица
`work_interval` из чужой ветки роняет `drop_all` в `conftest` («cannot drop table day because
other objects depend on it»). Прогон уведён в отдельную базу `habit_tracker_test_fast1`.

Feedback loops (backend): pytest **600/600 green** (было 574 в этой ветке), `ruff check` clean,
`ruff format --check` clean (129 файлов), `mypy --strict app` clean (93 файла), `alembic heads` —
одна голова `c4f6b8d0e2a5`, миграции тикет не заводит. Docker-демон не поднят, `make check`
целиком не отрабатывал и `docker compose up` не запускался: compose-файлы проверены
`docker compose config` (dev и dev+prod), воркер прогнан живьём вне контейнера — расписание
напечатано, настоящий `SIGTERM` в середине полуторасекундного задания дал выход через 1.13 с,
`job smoke done in 1.5s`. Фронтенд не тронут; `bun test` (682) и `bunx tsc --noEmit` прогнаны на
всякий случай, оба зелёные, `frontend/SESSION_REVIEW.md` не менялся.

---

## 2026-08-30 — PHASE-03/109: сессия для веб-клиента

Тикет: браузер меняет `API_KEY` на `HttpOnly`-куку и дальше ключа не видит; `X-API-Key` остаётся
рабочим для iOS, mac-агента и скиллов. Затронуто 8 файлов бэкенда (3 new, 5 mod) плюс два
compose-файла и `deploy/README.md`.

- `app/core/session.py` — **new**: подписанный сессионный токен на `itsdangerous.TimestampSigner`
  (соль `habit-tracker.web-session`, полезная нагрузка — константа `web` и метка времени) плюс
  установка и стирание куки. `session_token_is_valid` возвращает `False` на любую негодную строку:
  значение куки приходит от клиента, и испорченная подпись обязана дать 401, а не 500. Часы
  подписчика фиксируются параметром `issued_at` — ради теста «кука старше срока не пускает»,
  который иначе спит месяц или патчит `time.time` глобально.
- `app/api/auth.py` — **new**: `POST/GET/DELETE /api/v1/auth/session`. Роутер подключён **вне**
  периметра `require_api_key`: войти обязан клиент, у которого ещё нет ни ключа, ни куки. Ключ
  приходит телом, а не строкой запроса — та попадает в логи прокси и в историю браузера. В теле
  ответа нет ни ключа, ни токена, только `authenticated` и `expires_in_s`.
- `app/schemas/auth.py` — **new**: `SessionOpenRequest` (`api_key`, `min_length=1`) и `SessionState`.
- `app/core/auth.py` — **mod**: `require_api_key` принимает валидный `X-API-Key` **или** валидную
  куку; текст отказа один на обе схемы (`UNAUTHORIZED_DETAIL`), иначе по сообщению различались бы
  «ключ не тот» и «кука протухла». Выделены `auth_is_disabled`, `api_key_is_valid`,
  `session_cookie_is_valid` — ими же пользуется ручка входа.
- `app/core/config.py` — **mod**: `SESSION_SECRET`, `SESSION_MAX_AGE_S` (30 суток, `gt=0`),
  `SESSION_COOKIE_SECURE` (по умолчанию `true`). Пустой `SESSION_SECRET` при `ENVIRONMENT=prod`
  роняет сборку настроек тем же способом и тем же видом сообщения, что пустой `API_KEY` в `#106`.
  В разработке подставляется заведомо публичный `DEV_SESSION_SECRET` — иначе страница входа не
  работает из коробки.
- `app/main.py` — **mod**: роутер `auth` под общим префиксом и вне зависимости `require_api_key`.
- `tests/test_session_auth.py` — **new**, 25 тестов: обмен ключа на куку, отказ на неверном ключе,
  атрибуты по сырому `Set-Cookie` (`HttpOnly`, `Secure`, `SameSite=Lax`, `Max-Age`, `Path`),
  подделанная на один символ подпись, мусор вместо токена, чужой секрет, просроченная кука,
  повторный вход, `X-API-Key` без куки и поверх дохлой куки, статус, выход и повторный выход,
  отказ старта в проде. `base_url` у клиента — `https`: кука выпускается с `Secure`, и по http её
  не отправила бы ни банка httpx, ни браузер. Замена куки идёт через `replace_cookie` (очистка +
  установка): `cookies.set` кладёт вторую куку рядом с живой, и тест на подделку зеленел бы по
  неправильной причине.
- `tests/test_perimeter.py` — **mod**: `prod_settings` несёт `SESSION_SECRET` — иначе продовый
  периметр `#106` перестал бы собираться.
- `pyproject.toml` — **mod**: `itsdangerous>=2.2` в основных зависимостях (пакет с `py.typed`).
- `habit-tracker/docker-compose.yml`, `deploy/docker-compose.prod.yml`, `deploy/README.md` —
  **mod**: `SESSION_SECRET`, `SESSION_MAX_AGE_S`, `SESSION_COOKIE_SECURE`; раздел «Сессия
  браузера» — что смена секрета гасит все сессии разом (списка сессий не хранит никто) и почему
  `Secure` придётся выключить, если фронтенд отдаётся по http внутри tailnet.

Миграции тикет не заводит: сессия подписанная, таблицы под неё нет.

Feedback loops (backend): pytest **625/625 green** (было 600 в этой ветке), `ruff check` clean,
`ruff format --check` clean (133 файла), `mypy --strict app` clean (96 файлов), `alembic heads` —
одна голова `c4f6b8d0e2a5`. Docker-демон не поднят, `make check` целиком не отрабатывал; тесты
шли против локального постгреса `localhost:5432`, база `habit_tracker_test_fast1` (общая
`habit_tracker_test` держит таблицу `work_interval` из чужой ветки и роняет `drop_all`).

## 2026-08-30 — PHASE-03/134 роли становятся данными

Вертикаль без единой строки автоматики: справочник ролей, правила разметки, минуты и акты. Ручной
ввод первичен — `POST /api/v1/role-time-blocks` с кодом роли, числом минут и заметкой работает,
когда больше не работает ничего. Импортёры `#135`/`#136` позовут те же две записи, добавив к ним
`external_ref`; это единственная разница между ними и человеком.

- `app/models/role.py` — **new**: `role`, `role_rule`, `role_time_block`, `role_act`. Все
  перечислимые поля — `String`, не enum (проект уже заплатил за `fieldtype`). `CHECK (minutes > 0)`,
  частичные уникальные `(source, external_ref) WHERE external_ref IS NOT NULL` на обеих фактовых
  таблицах, `role_id` — `RESTRICT`, `rule_id` — `SET NULL` (потерять правило не значит потерять
  минуты).
- `app/roles/catalog.py` — **new**: четыре сида с долями 25/25/50 как гипотезой квартала;
  `unassigned` без цели — целиться в долю неотнесённой работы значит целиться не туда.
- `app/roles/matcher.py` — **new**: чистый резолвер. Меньший `priority` выигрывает, равенство
  доопределено меньшим `id` (иначе один и тот же образец дрейфует между ролями от прогона к
  прогону). Несовпадение — `None`, не исключение. Сломанный regex и незнакомый `matcher_kind`
  промахиваются и логируются по id правила; сам заголовок окна в лог не попадает (ADR-0020 B5).
- `app/crud/role.py` — **new**: идемпотентный `seed_roles` (тесты строят базу `create_all` и сидов
  миграции не видят), CRUD справочника и правил, `resolve_role` с падением в `unassigned`,
  `write_time_block`/`write_act` — чтение-затем-запись вместо `ON CONFLICT`: решение «не трогать»
  зависит от `confidence` **хранимой** строки, а система однопользовательская.
- `app/schemas/role.py` — **new**: словарь `act_kind` живёт здесь и растёт правкой схемы, а не
  миграцией. `minutes` намеренно без `gt=0` — ноль отвергает база.
- `app/api/roles.py` — **new**: `GET/POST/PATCH /roles`, `GET/POST/PATCH /role-rules`,
  `POST/PATCH/DELETE /role-time-blocks` и `/role-acts`, `GET /roles/day[/{date}]`. Отказ базы
  превращается в 422 контекстным менеджером, который оборачивает и flush, и commit; в ответ уходит
  имя constraint, но не сорвавшая его строка — в ней лежит заметка человека.
- `alembic/versions/2026_09_01_1400-d5a7c9e1f3b6_role_tables.py` — **new**: одна ревизия на четыре
  таблицы (порознь бесполезны), `down_revision = c4f6b8d0e2a5`, сид через `ON CONFLICT DO NOTHING`,
  рабочий `downgrade` (проверено вручную: downgrade снимает все четыре, upgrade возвращает с
  четырьмя ролями).
- `app/models/__init__.py`, `app/crud/__init__.py`, `app/main.py` — **mod**: регистрация моделей,
  crud-модуля и роутера в периметре API-key.
- `tests/test_role_matcher.py` — **new**, 13 тестов: конфликт двух правил в обоих порядках ввода,
  равный `priority`, промах, чужой источник, сломанный regex, неизвестный `matcher_kind`, четыре
  вида матчера.
- `tests/test_roles.py` — **new**, 24 теста: сид и его идемпотентность, `unassigned` вместо NULL
  (плюс прямая проверка `role_id IS NULL` в таблице), неудвоение по `(source, external_ref)`,
  переживание `confirmed` импортёра для минут и для актов, `minutes = 0` и `-30` через
  `IntegrityError` на flush, и API-слой: 90 минут на найм, акт «написан ADR», 422 на нулевые минуты
  и на неизвестный код роли, отказ битого regex при заведении правила.

Feedback loops (backend): pytest **662/662 green** (было 625 в этой ветке), `ruff check` clean,
`ruff format --check` clean, `mypy --strict app` clean (103 файла), `alembic heads` — одна голова
`d5a7c9e1f3b6`. Docker-демон не поднят, `make check` целиком не отрабатывал; тесты шли против
локального постгреса `localhost:5432`, база `habit_tracker_test_fast1` (общая `habit_tracker_test`
держит таблицу `work_interval` из чужой ветки и роняет `drop_all`). Миграция проверена на отдельной
базе `habit_migr_fast1`: upgrade → downgrade → upgrade.

## 2026-08-30 — PHASE-03/94 (неделя и диапазон дней)

Тикет `94-week-days-endpoint-and-life-page`: таблица `week` со снимком счётчиков,
`GET /api/v1/days?from&to` в форме прежнего `/api/days`, `GET/PUT /api/v1/weeks/{iso}`,
импорт `weeks/**/*.md`. Тронуто 12 файлов бэкенда.

- `app/day/week.py` — **new**: чистая ISO-арифметика недели (`iso_code`, `week_bounds`,
  `week_codes`). Часы здесь не читаются: «какое сегодня число» остаётся за
  `app/core/daytime.py`, а неделя выводится из переданной даты. `date.isocalendar()`, а не
  ручной `weekday()` + `timedelta`, — иначе 2027-01-01 не попадает в `2026-W53`.
- `app/models/week.py` — **new**: `week` (снимок с `computed_at`, четыре колонки прозы,
  генерируемый `search`) и `week_review_item` (воскресный чеклист строками, а не `- [ ]`
  внутри прозы).
- `app/crud/week.py` — **new**: `recompute_week` пишет только `won_days`, `total_days`,
  `streak_end` и `computed_at`; прозу не трогает никогда. `list_days` отвечает диапазоном,
  считая задачи через `app.crud.mark.task_counts` — второго определения «skipped выходит из
  знаменателя» в SQL не заводится. `get_week` идёт с `populate_existing`: оба писателя
  обходят ORM (upsert и bulk delete), и без этого чтение после записи вернуло бы состояние до неё.
- `app/schemas/week.py` — **new**: `DayListItem` ровно в пяти полях прежнего `/api/days`,
  `WeekIn` с `extra="forbid"` — счётчики прислать нельзя.
- `app/api/week.py` — **new**: `days_router` и `weeks_router`. Код, который не называет неделю
  (`2026-W99`), — 404; неделя без ретро — 200 с пустой прозой. Диапазон шире пяти лет
  отклоняется 422, а не сканируется.
- `alembic/versions/2026_09_01_1400-d5a7c9e1f3b6_week.py` — **new**: `down_revision`
  `c4f6b8d0e2a5` по фактическому `alembic heads` этой ветки; `downgrade` сносит обе таблицы
  и оба индекса.
- `app/imports/week_md.py` — **new**: файл недели по блокам — «Что мешало» и «Mgmt-ретро» в
  свои колонки, чеклист в строки, всё остальное в `retro_md`. Счётчики из прозы не берутся:
  «0 из 7» остаётся предложением, а колонки считает `recompute_week`.
- `app/imports/personal_os.py` — **mod**: `collect_weeks`, `_import_weeks`, `_recompute_weeks`,
  счётчики недель в отчёте, `WEEK_LINK_RE` — ссылка в `weeks/` теперь переписывается в
  `/week/2026-W35`, потому что у недели появился экран.
- `app/models/import_source.py` — **mod**: вид `week_md`.
- `app/main.py`, `app/models/__init__.py` — **mod**: роутеры в периметр API-key, модели в реестр.
- `tests/test_week.py` — **new**: 18 тестов — ISO-арифметика с краями года, неделя без ретро,
  пересчёт двигает счётчики и `computed_at` и не трогает текст, PUT заменяет чеклист,
  разбор файла недели.
- `tests/test_days_range.py` — **new**: 8 тестов — форма прежнего `/api/days` (набор полей
  сверяется как множество), три состояния вердикта, `done`/`total` по рабочим задачам,
  пустой и слишком широкий диапазон, ключ API.
- `tests/test_import_personal_os.py` — **mod**: три теста импорта недели плюс правка теста
  ссылок — ссылка в `weeks/` больше не остаётся текстом.
- `tests/fixtures/personal_os/weeks/2026/2026-W35.md` — **new**: фикстура недели.

Feedback loops (backend): pytest **604/604 green** (было 601), `ruff check` clean,
`ruff format --check` clean (133 файла), `mypy --strict app` clean (96 файлов),
`alembic heads` — одна голова `d5a7c9e1f3b6`. Docker-демон не поднят, `make check` целиком
**не отрабатывал**. Тесты шли против постгреса на localhost:5432 в базе
`habit_tracker_test_fast4`, а не `habit_tracker_test`: в общей базе лежали таблицы другой
ветки (`work_interval`), и `drop_all` фикстуры падал на внешнем ключе. Отдельная база —
обход коллизии параллельных веток, не свойство тикета.

## 2026-08-30 — PHASE-03/121 (быстрая отметка: справочник + один эндпоинт записи)

Тронуто 9 файлов бэкенда.

- `app/models/quick_mark.py` — **new**: `quick_marks` (кнопка: подпись, `(category_id, field_id)`,
  `kind`, `step`, `unit_label`, `hotkey`, порядок, флаги) и `quick_mark_events` (журнал: дельта
  или галка, источник, `idempotency_key`, `undone_at` под #124). Словари `kind`/`source` —
  константы модуля, из них же собраны CHECK-констрейнты и текст миграции. Уникальность хоткея —
  именованный частичный индекс `uq_quick_mark_hotkey` (`WHERE hotkey IS NOT NULL`): у постгреса
  частичного UNIQUE-констрейнта не существует вовсе.
- `app/schemas/quick_mark.py` — **new**: `QuickMarkCreate`, `QuickMarkResponse`,
  `QuickMarkTodayResponse` (справочник + состояние дня), `QuickMarkEventRequest`,
  `QuickMarkEventResponse`. В теле тапа нет ни `category_id`, ни `field_id`, ни `display_mode`.
- `app/crud/quick_mark.py` — **new**: валидация справочника списком причин (образец —
  `validate_metric_ops`), накопление инкремента через `entry_crud.checklist_entry_id` и
  `values.format_number`, срыв отдельной записью, состояние дня и запись события. День берётся
  вызовом `core.daytime.local_date(at)`; часов этот модуль не читает вообще — момент приходит
  аргументом, поэтому тест «00:30» проверяем без подмены времени.
- `app/api/quick_marks.py` — **new**: `GET /quick-marks?date=`, `POST /quick-marks`,
  `POST /quick-marks/{id}/events` с `Idempotency-Key` (повтор — 200 и то же `event_id`).
  Клиентский `entry_date` — сверка часов, а не адрес: расхождение с `local_date()` — 409.
- `app/models/entry.py` — **mod**: `ix_entries_category_date` — прямая цена горячего пути.
- `alembic/versions/2026_09_01_1600-e6b8d0f2a4c7_quick_marks.py` — **new**: обе таблицы, четыре
  индекса и индекс на `entries`; `downgrade` снимает всё это и не трогает данные.
  `down_revision = d5a7c9e1f3b6` — фактическая голова ветки на момент реализации.
- `app/main.py`, `app/models/__init__.py`, `app/schemas/__init__.py` — **mod**: роутер в периметр
  API-key, модели и DTO в реестры.
- `tests/test_quick_marks.py` — **new**: 25 тестов — пять тапов в одну строку, сумма в ответе,
  повтор ключа, срыв записью на тап, четыре отказа справочника (чужое поле, галка на числе,
  срыв на `build`, инкремент без шага), занятый хоткей, тап в 00:30 против `local_date()`,
  пустой справочник, состояние дня в справочнике, журнал, offline-SQL миграции в обе стороны,
  grep-тесты на PII и на отсутствие второй даты.

Feedback loops (backend): pytest **629/629 green** (было 604+25), `ruff check` clean,
`ruff format --check` clean (138 файлов), `mypy --strict app` clean (100 файлов),
`alembic heads` — одна голова `e6b8d0f2a4c7`. Docker не работает, `make check` целиком
**не отрабатывал**. Тесты — против постгреса на localhost:5432 в базе
`habit_tracker_test_fast4` (в общей `habit_tracker_test` по-прежнему лежат таблицы других
веток, и `drop_all` фикстуры падает на их внешних ключах). Обратимость миграции проверена не
только offline-SQL: на отдельной базе `habit_migrate_fast4` прогнаны `upgrade head` →
`downgrade -1` → `upgrade head`, и `alembic check` не видит расхождений между моделью и схемой
по новым таблицам.

Долг, названный вслух: `surface=agent` и undo (#124, #125) не делались; сидов справочника нет —
кнопки заводятся руками через `POST /quick-marks`, пока не приехал экран #125.
## 2026-08-30 — PHASE-03/91: время работы, `work_interval`

Тронуто 12 файлов: 5 новых, 7 изменённых.

- `app/day/work.py` — **new**: чистая арифметика минут. `IntervalSpan`, `span_minutes`,
  `day_work_minutes`; словарь `mode` (`work`/`off`) и `source` (`manual`/`agent`/`corrected`)
  живёт здесь, а модель и схема его читают, а не перепечатывают. Пустой день отвечает `None`,
  а не нулём — то же правило, по которому `fold_daily` возвращает `None` при нулевом счётчике.
  Открытый интервал считается до `now`, но не дальше конца своих суток, и границу отдаёт
  `day_bounds()`, а не собственная арифметика.
- `app/models/work_interval.py` — **new**: таблица. `CHECK (ended_at IS NULL OR ended_at >
  started_at)`, CHECK на `source` и `mode`, btree по `(day_date, started_at)`, GiST по
  `tstzrange(started_at, ended_at)`. Колонки под заголовок окна нет и не будет — граница
  приватности всей модели дня проходит здесь.
- `app/schemas/work_interval.py` — **new**: `AwareDatetime` отвергает момент без смещения;
  `corrected` объявить нельзя, в него переводит правка; `extra="forbid"` отвергает присланный
  заголовок окна, а не глотает его молча.
- `app/crud/work_interval.py` — **new**: день интервала спрашивается у `local_date(started_at)`
  и здесь не считается — `grep` по файлу не находит ни `day_start_hour`, ни `timezone`.
  Первая правка агентского интервала уносит его границы в `auto_*`, ставит `source='corrected'`
  и штампует `edited_at`; вторая границы двигает, предложение не трогает. Начало, уводящее
  интервал в чужой день, отвергается `IntervalNotOnDay` → 422.
- `alembic/versions/2026_09_01_1400-d5a7c9e1f3b6_work_interval.py` — **new**:
  `down_revision = c4f6b8d0e2a5` по фактическому `alembic heads` этой ветки. Прогнан
  upgrade → downgrade → upgrade на отдельной базе; `downgrade` снимает оба индекса и таблицу.
- `app/api/day.py` — **mod**: `GET/POST/PATCH/DELETE /day/{date}/work-intervals`; ответ дня
  получил блок `work` с интервалами и суммой.
- `app/crud/summary.py` — **mod**: `work_minutes` берётся у интервалов. Незакрытый день меряется
  живьём, `recompute_history` читает суммы всей истории одним запросом и переписывает
  `day_summary.work_minutes` измерением. День без интервалов сохраняет число, присланное в
  `POST /close`, — иначе история, закрытая до появления интервалов, потеряла бы свои цифры.
- `app/core/daytime.py` — **mod**: `now_utc()`. Не второе определение суток, а одно написание
  `datetime.now(timezone.utc)`: `local_date()` отвергает наивный момент, и у починки этого
  отказа должно быть одно правописание. `today_local()` теперь зовёт его же.
- `app/day/evaluate.py`, `app/schemas/day.py`, `app/models/__init__.py` — **mod**: словарь и
  документация под новый источник `work_minutes`.
- `tests/test_work_intervals.py` — **new**: 28 тестов. Чистая арифметика без постгреса
  (пустой день — `None`, пауза — ноль, открытый интервал упирается в конец своих суток,
  UTC и берлинское написание одного момента дают одну длину) плюс API: интервал руками,
  23:00-01:00 целиком в дне начала, перевёрнутый интервал отвергают и валидатор, и `CHECK`,
  исправленный агентский отдаёт оба значения, 4/4 задачи и девять часов дают `lost/overtime`,
  день без интервалов — `missing_data: ['work_minutes']`, в ответе дня нет ни одного заголовка
  окна (набор полей интервала сверяется целиком).

Feedback loops (backend): pytest **603/603 green** (было 575), `ruff check` clean,
`ruff format --check` clean (130 файлов), `mypy --strict app` clean (94 файла), `alembic heads` —
одна голова `d5a7c9e1f3b6`. Docker-демон не поднят, `make check` целиком **не отрабатывал**:
тесты шли против постгреса на localhost:5432, база `habit_tracker_test`; миграция проверена
отдельно на `habit_mig_91` тем же постгресом.

## 2026-08-30 — PHASE-03/111: чат отвечает одним ходом и переживает перезапуск

Тронуто 11 файлов бэкенда: 8 new, 3 mod (плюс `app/llm/client.py`, `app/api/deps.py`,
`app/main.py`, `app/core/config.py`, `app/models/__init__.py`, `app/crud/__init__.py`).

- `app/models/chat.py` — **new**: четыре таблицы темы. `chat_conversations` (день разговора,
  вид, подсказки `cli_session_id`/`cli_cwd`/`context_version` — заводятся здесь, включает `#112`),
  `chat_messages` (порядок несёт `seq`, а не `created_at`; `uq_chat_message_seq` делает дубль
  позиции ошибкой базы), `chat_plans` (`message_id` unique; `applied_summary_id` намеренно без
  внешнего ключа), `chat_retrievals`. Словари — плоские строки без PG-enum и CHECK, по образцу
  `display_mode`.
- `alembic/versions/…-e6b8d0f2a4c7_chat_conversation_tables.py` — **new**: одна ревизия на всю
  тему, `down_revision = d5a7c9e1f3b6` (фактическая голова ветки). Проверена вживую на отдельной
  базе `habit_tracker_migr`: upgrade → downgrade → upgrade; после downgrade ни одной из четырёх
  таблиц нет. `alembic check` на мигрированной базе не показывает расхождений по chat-таблицам —
  модель и миграция совпадают колонка в колонку.
- `app/llm/chat/client.py` — **new**: `ChatLLMClient.stream_turn(...) -> AsyncIterator[ChatChunk]`
  рядом с нетронутым `LLMClient.generate`. `ISOLATION_ARGS` — отдельная константа, потому что
  проверяется тестом целиком: `--tools ""` и `--setting-sources ""` вместе со значениями, плюс
  `CLAUDE_CONFIG_DIR` и фиксированный пустой cwd из настроек. stderr процесса — `DEVNULL`:
  там эхо промпта. Парсер `stream_event/content_block_delta/text_delta` и финального `result`;
  `input_tokens` = `input + cache_creation`, иначе проверка «первый ход дешевле тысячи» врёт.
  API-реализация — `messages.stream` через `AnthropicInsightsClient.sdk`.
- `app/llm/chat/prompt.py` — **new**: системный промпт чата, `CHAT_CONTEXT_VERSION`, `ChatTurn` и
  `render_transcript` (реплей одним промптом с подписями ролей).
- `app/crud/chat.py`, `app/schemas/chat.py`, `app/api/chat.py` — **new**: лента, разговор с
  сообщениями, ход по SSE. Ход не берёт `get_db`: контекст читается своей сессией, сессия
  отпускается, ответ пишется новой — это же закрывает долг
  `concern-charts-ai-followups.md`. 503 проверяется **до** записи реплики.
- `app/llm/client.py` — **mod**: подпись `generate` не тронута. Добавлены свойство `sdk` и
  ре-экспорт `AnthropicAPIError`, чтобы `app/llm/chat/` стримил без второго `import anthropic`:
  инвариант «SDK импортируется ровно в одном файле» держится грепом, а не памятью.
- `app/api/deps.py` — **mod**: `get_chat_llm_client` и `get_session_factory` (фабрика сессий для
  единственной ручки, которой нельзя держать соединение всю генерацию).
- `tests/test_chat_stream.py` — **new**, 15 тестов: порядок событий `delta*/usage/done`, ответ с
  счётчиками токенов, `seq` 1..4 на двух ходах, реплей всего разговора на втором ходу, чтение
  разговора после «перезапуска», 503 без бэкенда не оставляет строк, сбой бэкенда даёт `failed`
  с машинным кодом и сохраняет полученный текст, в событии `error` нет ни куска разговора; плюс
  два несущих: во время генерации не открыто ни одной сессии БД, и закрытый генератор пишет
  `interrupted` с уже полученным текстом.
- `tests/test_chat_cli_args.py` — **new**, 20 тестов: набор флагов изоляции целиком (включая
  дословную сверку состава — замер 282 против 52 555 токенов сделан именно на нём),
  `CLAUDE_CONFIG_DIR` и cwd доезжают до процесса, разговор уходит stdin, ненулевой код не
  протекает содержимым, разбор потока и игнор незнакомых строк.

Feedback loops (backend): pytest **638/638 green** (было 603; 35 из них — новые тесты чата),
`ruff check` clean, `ruff format --check` clean (139 файлов), `mypy --strict app`
clean (101 файл), `alembic heads` — одна голова `e6b8d0f2a4c7`. Docker-демон не поднят,
`make check` целиком **не отрабатывал**: тесты шли против постгреса на localhost:5432
(`habit_tracker_test`), миграция — на `habit_tracker_migr` тем же постгресом.

---

## 2026-08-30 — PHASE-03/117 удаление диалога и видимый расход подписки

Две неправды закрыты одним срезом. Кнопка удаления перестала быть враньём: `DELETE` уносит
строки всех четырёх таблиц каскадом `#111` **и** файл `.jsonl` сессии CLI. Расход подписки
перестал быть невидимым до первого 429: суммы токенов и медиана задержки едут и в детальной
ручке, и в ленте.

Тронуто 5 файлов бэкенда (2 new, 3 mod).

- `app/llm/chat/session_files.py` — **new**: где CLI держит файл сессии и как его снести.
  Путь считается так же, как его считает сам CLI (`<config>/projects/<cwd с дефисами>/<id>.jsonl`),
  и вынесен отдельной функцией: `#112` обязан возобновлять ровно тот файл, который удаление
  сносит. `remove_session_file` не бросает ни разу и возвращает машинный код — `removed`,
  `absent`, `no_session`, `outside_config_dir`, `remove_failed`. Проверок на выход за пределы
  две, а не одна: файл обязан лежать и внутри каталога конфигурации, и ровно в каталоге
  этого разговора — без второй подделанный `../<чужой проект>/<id>` снёс бы сессию соседа,
  формально оставаясь внутри `CHAT_CLAUDE_CONFIG_DIR`. Модуль лежит в `app/llm/chat/`, а не в
  `app/crud/` (как называл тикет): это знание об устройстве CLI на диске, и живёт оно рядом с
  клиентом, который этот `cwd` и задаёт.
- `app/crud/chat.py` — **mod**: `delete_conversation` (одна транзакция, каскад, файл — после
  коммита и никогда не поперёк удаления строк), `usage_statement`/`usage_by_conversation`/
  `usage_of` и `ConversationUsage`. Свёртка — один запрос с `GROUP BY` на всю ленту, а не
  запрос на строку, и `content` в него не входит: пятьдесят разговоров иначе тянут через сеть
  весь свой текст ради трёх чисел в шапке. Медиана — `percentile_cont(0.5) WITHIN GROUP`, а не
  среднее: один длинный ответ сдвигает среднее так, что «сколько обычно ждать» по нему не
  читается. Единственный `type: ignore` — на `within_group`: упорядоченные агрегаты не покрыты
  стабами SQLAlchemy, а замена ему — `text()`, который не проверяется ничем.
- `app/api/chat.py` — **mod**: `DELETE /chat/conversations/{id}` (204, 404 на несуществующий),
  расход в теле `GET /conversations/{id}` и в каждой строке `GET /chat/conversations`. У
  созданного разговора расход — `EMPTY_USAGE`, а не запрос в базу за нулями.
- `app/schemas/chat.py` — **mod**: `ConversationUsage` и поле `usage` у `ConversationResponse`
  (а значит, и у `ConversationDetail`).
- `tests/test_chat_delete.py` — **new**: 21 тест. Каскад проверяется счётом строк во всех
  четырёх таблицах, а не ответом ручки; файловая часть — на настоящем временном каталоге,
  подставленном в `settings.CHAT_CLAUDE_CONFIG_DIR` (мок `unlink` проверял бы мок).
  Отдельно: подделанный id наружу (`../../../hostage.jsonl` остаётся на диске), подделанный id
  в соседний проект, разговор без сессии вовсе, разговор с пропавшим файлом, квитанция
  `applied_daily_summaries` переживает удаление разговора, соседний разговор не задет, свёртка
  сходится с `SELECT sum(...)`, медиана двух замеров — среднее между ними, и `content` не
  встречается в скомпилированном SQL свёртки.

Найдено по ходу и починено здесь же: `chatAPI.streamMessage` во фронте ходил без
`credentials: 'include'` — ход чата после `#109` уезжал бы в 401. Это стык двух веток, а не
дефект одной.

Feedback loops (backend): pytest **745/745 green** (было 725), `ruff check` clean,
`ruff format --check` clean (158 файлов), `mypy --strict app` clean (115 файлов),
`alembic heads` — одна голова `e6b8d0f2a4c7`, `alembic upgrade head` на чистой базе проходит
всю цепочку. Docker-демон не поднят, `make check` целиком не отрабатывал: pytest гонялся
обходом через `localhost:5432` в базе `habit_tracker_test_fast1` (общая `habit_tracker_test`
занята параллельными worktree). Миграций тикет не заводит.

## 2026-08-30 — PHASE-03/113 (чат видит день)

Тронуто 6 файлов бэкенда: 2 новых, 4 изменённых.

- `app/llm/chat/context.py` — **new**: `build_day_card(db, entry_date)` и реестр секций
  `DAY_CARD_SECTIONS`. Секция описана `SectionSpec(name, title, priority, build)`, добавление
  новой стоит строку в кортеже. Строитель возвращает `None` — секции нет вовсе (источник ещё
  не приехал), пустой список — секция есть и говорит «записей нет». Потолок держится
  выбыванием строк с хвоста наименее приоритетной секции; срез строки остался последним
  рубежом на случай потолка ниже, чем сумма подписей. Секции сегодня: план дня с отметками
  (`crud/plan` + `crud/mark`), дневные свёртки здоровья (тот же `health_crud.daily_values`,
  которым отвечает `GET /health/metrics`), записи трекера (`crud/table`), дневник
  (`crud/journal`, блокнот дня — та же строка, второй секции не получает).
- `app/llm/chat/prompt.py` — **mod**: `compose_system_prompt(day_card)` — единственная склейка
  «правила + карточка», `CHAT_CONTEXT_VERSION` 1 → 2, текст промпта переписан под карточку
  (один день, «записей нет» значит именно это, пометка об обрезке — не отсутствие данных).
- `app/api/chat.py` — **mod**: карточка строится той же сессией, что записывает вопрос;
  `_TurnContext` вместо кортежа из двух; `GET /chat/conversations/{id}/context` отдаёт текст,
  размер, потолок, признак обрезки и имена выбывших секций; ход приводит разговор к текущей
  версии контекста.
- `app/crud/chat.py` — **mod**: `reset_stale_context` — смена версии стоит `cli_session_id`,
  а не разговора.
- `app/schemas/chat.py` — **mod**: `ConversationContext`.
- `app/core/daytime.py` — **mod**: `local_time(at)` — настенные часы сохранённого момента на
  той же опубликованной границе, которую читает `local_date`. Понадобилось, чтобы окно пункта
  плана печаталось как 09:00–10:00, а не как UTC; второй зоны в приложении не завелось.
- `tests/test_chat_day_card.py` — **new**: 13 тестов. Пустой день (каждая секция говорит
  «записей нет», в теле карточки нет ни одной цифры), секция без источника отсутствует
  целиком, дневная свёртка совпадает с `GET /health/metrics` (число вынимается из карточки
  разбором строки, а не форматтером из того же кода), почасовых слагаемых в карточке нет,
  день с 50 записями и дневником на 20 000 знаков влезает в `CHAT_CONTEXT_MAX_CHARS`,
  карточка кончается целой строкой-пометкой, порядок выбывания секций по приоритету,
  `/context` отдаёт текст, посимвольно лежащий в системном промпте хода, 404 на чужой id,
  устаревшая версия контекста теряет подсказку сессии и не ломает разговор, план и отметка
  видны в карточке.
- `tests/test_chat_stream.py` — **mod**: проверка промпта сравнивает композицию
  `compose_system_prompt`, а не голую константу; прямой вызов `_turn_events` получил
  `system_prompt`.

Feedback loops (backend): pytest **757 passed, 1 failed**. Упавший —
`test_insights.py::TestBuildPeriodContext::test_context_includes_table_and_journal_data`,
падает и на чистой ветке (проверено `git stash`), к этому тикету отношения не имеет.
`ruff check` clean, `ruff format --check` clean (160 файлов), `mypy --strict app` clean
(116 файлов), `alembic heads` — одна голова `e6b8d0f2a4c7`. Docker не поднят, `make check`
целиком не отрабатывал: pytest гонялся обходом через `localhost:5432`, база
`habit_tracker_test_fast1` (в общей `habit_tracker_test` лежит таблица `quick_mark_events`
из соседней ветки, и `drop_all` по метаданным этой ветки на ней падает). Миграций тикет
не заводит.
## 2026-08-31 — PHASE-03/112 (возобновление сессии CLI с реплеем)

Тикет `112-chat-resume-with-replay-fallback`: второй ход продолжает сессию CLI вместо того,
чтобы платить за весь диалог заново, и падает обратно в реплей при любой поломке. Миграции
тикет не заводит — `cli_session_id`, `cli_cwd` и `context_version` пришли с `#111`.

Ветка начата слиянием `fast-3`: `#111` уехал туда, и `app/llm/chat/client.py`, который правит
этот тикет, на `fast-4` отсутствовал. Слияние развело столкнувшиеся ревизии Alembic —
обе ветки выдали `d5a7c9e1f3b6` и `e6b8d0f2a4c7` разным темам. Цепочка выпрямлена:
work_interval → chat → week (`f7c9b1d3a5e2`) → quick_marks (`a8d0c2e4b6f1`).

- `app/llm/chat/session.py` — **new**: где CLI держит сессию (`<config>/projects/<слаг-cwd>/
  <id>.jsonl`, слаг — каждый символ вне `A-Za-z0-9-` в дефис) и чистый предикат `can_resume`
  из четырёх условий: id есть, cwd совпал, `context_version` совпал, файл на месте.
  `choose_strategy` поверх него отдаёт `TurnStrategy` — на реплее с новым uuid, который уйдёт
  в `--session-id`. Ни одна непройденная проверка не отказывает: все ведут в реплей.
- `app/llm/chat/client.py` — **mod**: развилка внутри `stream_turn`. Первый ход открывает
  сессию нашим uuid (`--session-id`), последующие продолжают (`--resume`); промпт продолжения
  — только хвост после последней реплики модели, промпт реплея — весь разговор. `_with_session`
  подставляет в итог хода тот id, под которым ход запускали, когда CLI промолчал: иначе первый
  ход не оставляет ничего, что мог бы продолжить второй. `resumes(hint)` вынесен в контракт
  базового класса — шапку разговора считает транспорт, а не второй экземпляр тех же условий.
- `app/llm/chat/prompt.py` — **mod**: `resume_tail` и `render_resume`. Одинокая реплика человека
  уходит в продолжаемую сессию без подписи «Человек:» — это настоящая реплика пользователя;
  заметка сервера, легшая между ходами, едет вместе с ней и не теряется.
- `app/crud/chat.py` — **mod**: `touch_conversation` пишет `context_version` вместе с id сессии,
  `drop_stale_session` обнуляет id при расхождении версий. Пустая подсказка не затирает
  заполненную: ход на API-бэкенде не имеет права стереть сессию CLI вчерашнего дня.
- `app/api/chat.py` — **mod**: подсказка читается до хода (устаревшая версия чистится там же,
  чтобы таблица и `ResumeHint` не расходились ни на миг), уходит в транспорт, id сессии
  возвращается в таблицу. `GET /conversations/{id}` отдаёт `resume_ready`.
- `app/schemas/chat.py` — **mod**: `resume_ready` в `ConversationDetail`.
- `tests/test_chat_resume.py` — **new**, 27 тестов: слаг и путь к файлу сессии; четыре условия
  продолжения, каждое ломается отдельно (нет id, файл удалён, cwd уехал, версия сменилась,
  бэкенд без каталога); что уходит в промпт на продолжении и на реплее; подставной процесс CLI
  — `--session-id` на первом ходу, `--resume` со старым id на втором и одна строка в stdin,
  удалённый файл возвращает в промпт число `4271`, `result` без `session_id` всё равно называет
  сессию; десять ходов подряд и ни один не унёс сумму предыдущих; ход через ручку пишет
  сессию/cwd/версию, второй ход получает подсказку первого, API-бэкенд после пяти ходов
  оставляет `cli_session_id` пустым, смена `CHAT_CONTEXT_VERSION` обнуляет id и реплей несёт
  то же число; реплей идёт по `seq`, а не по `created_at` (две строки с перевёрнутым временем);
  `resume_ready` в трёх состояниях.
- `tests/test_chat_cli_args.py`, `tests/test_chat_stream.py` — **mod**: подписи под новый
  параметр `resume` и под `build_argv(prompt, strategy)`.
- `tests/test_insights.py` — **mod**, чужая находка по ходу: тест звал `date.today()`, тогда как
  окно контекста считает `today_local()`. Между полуночью и часом начала дня это разные числа,
  и тест краснел по времени суток. Второе определение «какое сегодня число» убрано.

Feedback loops (backend): pytest **719/719 green**, `ruff check` clean, `ruff format --check`
clean (154 файла), `mypy --strict app` clean (112 файлов), `alembic heads` — одна голова
`a8d0c2e4b6f1`. Docker-демон не поднят, `make check` целиком **не отрабатывал**: тесты шли
против постгреса на localhost:5432 (`habit_tracker_test`). Живого прогона `claude -p --resume`
не было — запуск CLI из этой сессии не разрешён; наличие флагов сверено по `claude --help`.

## 2026-08-31 — PHASE-03/143, закрытие дня в два касания

Тронуто 7 файлов бэкенда.

Долг, названный вслух: `surface=agent` и undo (#124, #125) не делались; сидов справочника нет —
кнопки заводятся руками через `POST /quick-marks`, пока не приехал экран #125.

---

## 2026-08-30 — PHASE-03/142 канон дня данными: карта дня в `day_rule_set`, формула вердикта строкой

Тронуто 10 файлов бэкенда, из них 2 новых.

- `alembic/versions/2026_09_01_1400-d5a7c9e1f3b6_day_rule_set_generator_columns.py` — **new**:
  пятнадцать колонок к `day_rule_set` — края дня временами (`wake_at` 06:00, `work_start` 07:45,
  `review_at` 15:40, `bedtime_max` 22:30), свободный вечер 19:10-21:00, вечер с близкими
  18:30-21:00 и флаг к нему, `overtime_lost_min` 600, `max_study_items` 2, `days_off`,
  `hard_edge_kinds`, `anchors`, `verdict_rule`. Сид обеих строк — в теле миграции, без импорта
  из `app/`. Действующая строка получает якорь `relationship`, legacy — нет: вечер с близкими
  стал требованием канона вместе с этим тикетом, и день до 2026-08-17 им не судится.
  `downgrade()` снимает ровно эти пятнадцать и оставляет таблицу в виде [#86] — прогнано вживую
  (upgrade → downgrade → upgrade на базе `habit_migr_fast2`).
- `app/models/day.py` — **mod**: те же колонки моделью, JSONB для четырёх списков/словаря, у
  каждой python-side `default` рядом с `server_default` — иначе строка, собранная в памяти
  тестом, тянула бы ленивую догрузку в async-контексте.
- `app/day/rules.py` — **mod**: `DayMap`, `DayEdge`, `Interval` и `day_map(rule)` — вся карта
  дня одним объектом; `RuleSeed` и оба сида дополнены. Спорт — край без часа (`at=None`):
  канон ставит его до работы, но минуты для него не называет, и выдуманные 06:15 были бы
  числом, которого никто не решал.
- `app/day/evaluate.py` — **mod**: `verdict_reasons(rule)` читает порядок условий из
  `verdict_rule.reason_order`, `evaluate_day` идёт по нему, а не по фиксированной лесенке;
  состав якорей берётся из `anchors`. `DayFacts.anchor_kinds` — какие виды якорей день закрыл;
  `None` значит «состав не измерен» (у плана якоря без кодов, справочник приезжает с [#92]) и
  уходит в `missing_data` кодом `anchor_kinds` — тем же способом, что и неизмеренные минуты.
  Опечатка в формуле не проглатывается: `UnknownVerdictReason`.
- `app/day/plan_validate.py` — **mod**: `check_hard_rigidity` берёт разрешённые виды из
  `rule.hard_edge_kinds`; `HARD_ALLOWED_KINDS` остаётся ответом для строки без колонки.
- `app/crud/mark.py` — **mod**: `closed_anchor_kinds` — виды якорей, закрытых днём, по кодам
  пунктов плана; `None`, когда план не назвал ни одного (пустое множество означало бы «ни
  одного якоря не закрыто» и снимало бы день).
- `app/crud/summary.py`, `app/crud/day.py`, `app/schemas/day.py`, `app/api/day.py` — **mod**:
  факты дня получают состав якорей, сид переносит новые поля, `GET /day/{date}` отдаёт блок
  `day_map`.
- `tests/test_day_rules_generator_columns.py` — **new**: 18 тестов — карта дня числами строки,
  край без часа, снятие флага вечера с близкими, вердикт по составу якорей, тот же прожитый
  день под двумя строками, неизмеренный состав, формула порядком строки, опечатка в формуле,
  `hard_edge_kinds` из строки, оба сида, `day_map` по HTTP, 404 на дату вне периодов и полный
  прогон «новая строка не двигает вчерашний вердикт» через закрытие и пересчёт истории.
- `tests/test_day_close.py` — **mod**: два ожидания `missing_data` — у планов этих дней якоря
  без кодов, поэтому состав не измерен и день говорит об этом вслух.
- `tests/test_plan_constraints.py` — **mod**: утка `_Rule` получила `hard_edge_kinds`.

Решение, которое стоит назвать вслух: `hard_edge_kinds` — это **виды пунктов**
(`anchor`, `hard_point`), а не пять якорей из иллюстрации ADR-0015. Те пять уже лежат в
`required_anchors`, а решение человека от 2026-08-30 разрешает жёсткость всему `hard_point`.

Feedback loops (backend): pytest **593/593 green**, `ruff check app tests` clean,
`ruff format --check` clean, `mypy --strict app` clean (90 файлов), `alembic heads` — одна
голова `d5a7c9e1f3b6`. `make check` целиком не отрабатывал: docker-демон не отвечает. Тесты шли
против постгреса на localhost:5432 в отдельной базе `habit_tracker_test_fast2` — в общей
`habit_tracker_test` лежит `work_interval` из параллельной ветки, и `drop_all` спотыкается о
её внешний ключ на `day`.
- `alembic/versions/2026_09_02_1000-b9e1d3f5a7c2_day_summary_stage_and_idempotency.py` —
  **new**: `stage` (`open`/`reviewed`/`closed`, server_default `closed`), `reviewed_at` и два
  ключа идемпотентности на `day_summary`; `CHECK` на словарь стадий и `CHECK` «вердикт только
  на закрытом дне»; по unique на каждый ключ. `downgrade()` снимает четыре колонки и четыре
  ограничения, вердиктов и прозы не касается. Прогнана вживую: `upgrade` → `downgrade -1` →
  `upgrade` на чистой базе `habit_migrate_fast4`.
- `app/models/summary.py` — **mod**: стадия и ключи как колонки, два новых `CHECK`. Отдельной
  таблицы `day_closing` из ADR-0015 не заводится — итог дня уже целиком в этой строке.
- `app/schemas/summary.py` — **mod**: `DayReviewIn` (касание 15:40) рядом с `DayCloseIn`; `null`
  в теле теперь «не трогать», а не «стереть»; ответ несёт `stage`, `reviewed_at`,
  `review_skipped`. Вердикта в теле приёма нет ни у одного касания — `extra="forbid"` даёт 422.
- `app/crud/summary.py` — **mod**: `review_day` рядом с `close_day`, обе двигают одну строку
  через общий `_store`; ключ ищется до записи, повтор ничего не пишет, чужая дата поднимает
  `KeyBelongsToAnotherDay`. Пересчёт истории теперь знает стадию: полузакрытый день не носит
  стрика и не принимает переопределения. Починена ловушка на стыке Core-upsert и ORM: строка,
  уже загруженная в сессию, после `pg_insert` оставалась старой, и `recompute_history`
  записывала прежние цифры поверх только что сохранённых — после записи строка обновляется.
- `app/api/day.py` — **mod**: `POST /day/{date}/close/review` и `.../close/final`, оба с
  `Idempotency-Key` и 409 на ключ с чужой даты; старый `POST /day/{date}/close` помечен
  `deprecated` и зовёт `final`, а не повторяет его.
- `app/imports/personal_os.py` — **mod**: импорт называет `stage='closed'` явно. Иначе импорт
  поверх дня, у которого сегодня было только касание 15:40, упирался бы в `CHECK`.
- `tests/test_day_close_two_touches.py` — **new**, 18 тестов: стадии `open → reviewed → closed`,
  живой пересчёт полузакрытого дня, повтор с тем же ключом (и `updated_at` на месте), другой
  ключ и одна строка, ключ ревью отдельно от вечернего, чужая дата → 409, ревью после закрытия
  не откатывает день, `verdict` в теле → 422, закрытие вчера двигает стрик сегодня, записка
  переопределения переживает перезакрытие, устаревшая ручка — синоним `final`.

Feedback loops (backend): pytest **737/737 green**, `ruff check` clean, `ruff format --check`
clean (155 файлов), `mypy --strict app` clean (112 файлов), `alembic heads` — одна голова
`b9e1d3f5a7c2`. `make check` целиком **не отрабатывал**: docker-демон на машине не поднят,
тесты шли обходом против постгреса на localhost:5432 (база `habit_tracker_test_fast4` — общая
`habit_tracker_test` занята соседними дорожками роя, и `drop_all` в ней падал на чужих
таблицах).
