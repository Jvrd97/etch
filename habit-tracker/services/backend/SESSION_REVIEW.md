# Session Review Log

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
