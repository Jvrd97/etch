# Session Review Log

## 2026-08-31 — PHASE-03/147 нарушения правил на экране дня

- `lib/api.ts` — **mod**: типы `PlanRuleCode`, `PlanViolation`; `dayAPI.violations`, `dayAPI.buildSkeleton`.
- `lib/plan-violations.ts` — **new** (+тест): `violationsByItem` (поиск строго по id — текста в нарушении нет и не будет), `planWideViolations` (правила, у которых нарушивший пункт — тот, которого нет), `ruleLabel`, `planAuthorLabel`.
- `hooks/useDay.ts` — **mod**: нарушения тянутся рядом с днём; их падение не гасит день.
- `components/day/PlanSections.tsx` — **mod**: пункт с `warn` помечен расшифровкой правила и по-прежнему рисуется и отмечается.
- `components/DayScreen.tsx`, `components/mobile/MobileDayScreen.tsx` — **mod**: в шапке плана — кем он собран (по колонке `source`, а не по заголовку); правила, не привязанные к строке, показаны над планом.
- `components/day/PlanSections.test.tsx`, `hooks/useDay.test.ts`, `components/DayScreen.test.tsx` — **mod**: помеченный пункт, непомеченный пункт, план без нарушений вовсе; моки `useDay` и `dayAPI` получили новые члены.

Проверки: `tsc --noEmit`, `eslint .` (0 problems), `bun test` — 860 passed.

## 2026-08-31 — PHASE-03/124 отмена тапа

- `lib/api.ts` — **mod**: `quickMarksAPI.tap` принимает `Idempotency-Key`; `quickMarksAPI.undo`, `quickMarksAPI.sources`; типы `QuickMarkUndo`, `QuickMarkSourceUsage`.
- `lib/quick-marks.ts` — **mod**: `applyQuickMarkUndo`, `undoCaption`, `newTapKey`.
- `hooks/useToday.ts` — **mod**: тап шлёт ключ и повторяет неудавшуюся отправку **тем же** ключом; `lastQuickMarkEvent` и `undoLastQuickMark`; снимок с сервера гасит предложение отмены.
- `components/QuickMarkRow.tsx` — **mod**: «Отменить «<кнопка>»» в той же строке, появляется только после тапа.
- `app/today/page.tsx`, `app/m/today/page.tsx` — **mod**: оба шелла передают `lastEvent` и `onUndo`.
- `hooks/useToday.test.ts`, `components/QuickMarkRow.test.tsx`, `lib/quick-marks.test.ts` — **mod**: повтор под одним ключом, два тапа — два ключа, отмена одним действием, отказ гасит предложение и оставляет сумму, отмены нечего предлагать после неудавшейся отправки.
- 25 sibling test-файлов — **mod**: в mock `@/lib/api` добавлены `quickMarksAPI.undo` и `.sources` (bun фиксирует набор export-имён при первом линке).

Проверки: `tsc --noEmit`, `eslint .` (0 problems), `bun test` — 845 passed.

## 2026-07-24 — round 3 review fixes (frontend, тикет PHASE-01/40)

Раунд 3 по замечаниям ревью. Работа отнесена к слайсу `issues/PHASE-01/in-work/40-mobile-shell-toggle-manifest-today.md` — правятся именно его файлы; служебного ticket-id `PHASE-01/round-2-review-fixes` в маркерах больше нет.

Файлов тронуто: 6 (3 new, 3 mod).

- `hooks/useRefreshOnVisible.ts` — **mod**: публичный интерфейс сужен до самого хука. `DOCUMENT_REFRESH_EVENTS`, `WINDOW_REFRESH_EVENTS`, `ListenerTarget`, `VisibilityDocument`, `VisibilityTargets` и `subscribeOnVisible` были экспортированы только ради тестов и стали module-private. Устранён двойной рефетч: возврат на вкладку поднимает и `visibilitychange`, и `focus` (разными тасками), поэтому рефреши ближе `REFRESH_DEDUPE_MS = 250` схлопываются в первый — на `/table` это был второй параллельный набор запросов.
- `hooks/useRefreshOnVisible.test.ts` — **mod**: тесты переписаны на сам хук через `renderHook` — один рефреш на возврат (красный до дедупа: 3 вызова), повторный рефреш после окна, игнор событий при `visibilityState === 'hidden'`, снятие слушателей на unmount, ре-подписка при смене идентичности `refresh`, SSR-рендер без `document`/`window`.
- `hooks/useToday.ts` — **mod**: у `loadData` появился параметр `{ showSpinner }`. `setLoading(true)` остался только у первичной загрузки в `useEffect`; в `useRefreshOnVisible` уходит стабильный `refresh`, который перечитывает данные молча — старый снимок остаётся на экране, пока не приедет новый.
- `hooks/useToday.test.ts` — **new**: спиннер на первичной загрузке; рефетч по `visibilitychange` не поднимает `loading` и не сбрасывает уже загруженные `entries` (тест был красным: `loading` = true в полёте).
- `test-setup.ts` — **new**: preload для `bun test` — регистрирует happy-dom-глобалы и `IS_REACT_ACT_ENVIRONMENT`, без них React-хуки не отрендерить.
- `bunfig.toml` — **new**: подключает preload. Добавлены dev-зависимости `@testing-library/react` и `@happy-dom/global-registrator`.

**Review-маркеры.** 33 файла, переведённые в `[review:approved]` прошлым раундом без внешнего ревью, возвращены в `[review:need-review]` (CLAUDE.md §9: approved — результат пройденного ревью, а не шаг имплементации).

Feedback loops: `tsc --noEmit` clean, eslint clean, `bun test` 170/170 green, `next build` green (14 маршрутов) — включая сборку чистого чекаута только из tracked-файлов.

## 2026-07-24 — round 2 review fixes (frontend)

Раунд 2 по замечаниям ревью. Ревьюеру передаётся диапазон `fa04170..HEAD`; frontend-часть диапазона — коммит `a8d75ed` против тикета `issues/PHASE-01/in-work/40-mobile-shell-toggle-manifest-today.md`.

Файлов тронуто: 5 (2 new, 3 mod).

- `hooks/useRefreshOnVisible.ts` — **new**: общий хук «перечитать данные, когда вкладка/приложение снова видимы». Внутри — чистая `subscribeOnVisible(refresh, {doc, win})`, вынесенная ради тестируемости без DOM. `visibilitychange` вешается на `document`, `focus` и `pageshow` — на `window` (они не всплывают до документа, поэтому регистрируются отдельно); события, пришедшие при `visibilityState !== 'visible'`, игнорируются, чтобы фоновая вкладка не слала запросы.
- `hooks/useRefreshOnVisible.test.ts` — **new**: 5 unit-тестов (сначала красные) — подписка на все три события, раскладка document/window, вызов refresh при видимом документе, игнор при скрытом, снятие ровно тех же handler-ов по идентичности.
- `hooks/useToday.ts` — **mod**: подключён `useRefreshOnVisible(loadData)`. Это фикс замечания: в standalone-PWA документ не перезагружается, и `/m/today` показывал снимок данных с момента запуска приложения.
- `app/table/page.tsx` — **mod**: ручной `useEffect` с тремя `addEventListener`/`removeEventListener` заменён на тот же хук — поведение прежнее, дублирование убрано.
- `lib/chart-utils.ts` — **mod**: `previousDay` больше не форматирует дату руками через `.toISOString().split('T')[0]`, а зовёт `toISODate` из `lib/date` — единственный источник правды по `YYYY-MM-DD`.

**Review-маркеры.** 33 файла диапазона переведены в `[review:approved]`. `app/table/page.tsx` и `hooks/useToday.ts` оставлены в `need-review`: в них лежат незакоммиченные правки этого раунда.

Feedback loops: `tsc --noEmit` clean, eslint clean, `bun test` 167/167 green, `next build` green (14 маршрутов).

## 2026-07-23 — PHASE-01/10-ios-dashboard (round 2, web-часть паритета)

Раунд 2 по ревью. Веб-фронтенд затронут ради паритета счётчиков и ленты с новым iOS-дашбордом. Кода не менялось сверх того, что уже было заведено в раунде 1, — фиксируется продуктовое решение и подтверждается корректность.

Продуктовое решение по счётчику Entries (был блокер: расхождение iOS vs web). Выбран **вариант (b)** — прежнее web-поведение признано багом: карточка Entries считала `entries.length` от лимитированной выборки `getAll({limit:5})`, из-за чего при >5 записях число капалось на 5, тогда как iOS показывал реальный total. Исправлено на реальный total: `app/page.tsx` грузит `entriesAPI.getAll()` без лимита (бэкенд-дефолт `limit=100`, тот же путь, что и iOS `fetchEntries(categoryId: nil)`), а `entriesCount` = длина полного списка. iOS оставлен как есть. Теперь обе платформы при >5 записях показывают одинаковое число (совпадают вплоть до бэкенд-дефолта 100). `journal.total` берётся из ответа независимо от лимита выборки, поэтому журнальная карточка не затронута.

Порядок ленты recent-activity (был warning). Бэкенд `GET /entries` отдаёт `order_by(Entry.entry_date.desc())` по умолчанию — это совпадает с date-desc. Дополнительно обе платформы пересортировывают ленту на клиенте по (`entry_date` desc, `id` desc на равных датах) — `computeDashboardStats` на web и `DashboardViewModel.aggregate` на iOS, — поэтому порядок и разрыв тай-брейков идентичны вне зависимости от порядка тай-брейка на бэке. Ленты не расходятся.

UX-паритет ленты (был warning). Обе платформы показывают одинаковый набор: `Entry #<id>`, сырой `entry_date` и счётчик `N values`. Web не показывает имя категории или форматированные значения — довидение iOS до web-презентации не требуется, паритет уже есть.

Файлов тронуто: 3 (2 new, 1 mod) — все от раунда 1, здесь только подтверждены.

- `lib/dashboard-stats.ts` — **new** (round 1): чистая агрегация — `entriesCount` = реальная длина списка (не лимит-срез), лента newest-first (date desc, id desc) с капом `RECENT_ENTRIES_LIMIT = 5`. Паритет с `DashboardViewModel.aggregate`.
- `lib/dashboard-stats.test.ts` — **new** (round 1): 4 unit-теста (реальный total при 12 записях, кап+порядок ленты с тай-брейками, отсутствие мутации входа, пустой список).
- `app/page.tsx` — **mod** (round 1): `entriesAPI.getAll()` без лимита + `computeDashboardStats`; карточка Entries и hero-кольцо используют реальный total.

Feedback loops: bun test 48/48 green, `tsc --noEmit` clean, eslint clean.

## 2026-07-22 — PHASE-01/25-ai-reports-history

Тикет: история AI-отчётов (`/insights`) и выбор периода разбора на Dashboard. Frontend-часть: затронуто 5 файлов (2 new, 3 mod); backend-часть описана в `services/backend/SESSION_REVIEW.md`.

- `lib/api.ts` — **mod**: `insightsAPI.getAll` (GET /insights/) и `insightsAPI.getById` (GET /insights/{id}) + тип `AIReportListItem` (id, period_days, model, created_at, preview).
- `components/InsightMarkdown.tsx` — **new**: минимальный MD-рендерер отчёта (headings/bullets/paragraphs), вынесен из `app/page.tsx` для переиспользования.
- `app/insights/page.tsx` — **new**: карточки истории отчётов (период, дата, модель, превью) с разворачиваемым полным просмотром; состояние просмотра — discriminated union `ReportView`; empty state со ссылкой на Dashboard.
- `app/page.tsx` — **mod**: сегмент-селектор периода 7/30/90 (`INSIGHT_PERIOD_OPTIONS`) рядом с кнопкой «Разбор периода», период уходит в `insightsAPI.create(insightPeriod)`; ссылка «История» → `/insights`; локальный InsightMarkdown заменён импортом.
- `components/Navigation.tsx` — **mod**: пункт Insights (`/insights`, иконка Sparkles).

Feedback loops: tsc --noEmit clean, eslint clean, bun test 27/27 green, next build green (роут `/insights` static).

## 2026-07-22 — PHASE-01/20-category-page-chart

Тикет: страница категории `/categories/[id]` с мультилинейным per-day графиком (Recharts): линии по number/time-полям, две Y-оси при разных единицах, легенда с toggle видимости, периоды 7/30/90/всё без перезагрузки (данные за год из GET /table/ режутся на клиенте). Затронуто 6 файлов (3 new, 3 mod).

- `lib/chart-data.ts` — **new**: чистые функции — `chartableFields`, `buildSeries` (единицы: time→min, number→"(unit)" из имени; первая единица→left, остальные→right), `parseCellValue` (HH:MM[:SS]→минуты), `buildChartData`, `sliceByPeriod`, `chartDateRange`; палитра серий провалидирована dataviz-валидатором на поверхности `#1a1a1a`.
- `lib/chart-data.test.ts` — **new**: 10 unit-тестов (bun:test) на все чистые функции, писались first (red→green).
- `components/CategoryChart.tsx` — **new**: LineChart с двумя YAxis (правая рендерится только при второй единице), кнопки периодов, кастомная легенда-кнопки с toggle (`hide` у Line), tooltip с единицами.
- `app/categories/[id]/page.tsx` — **new**: заголовок категории + график; параллельная загрузка `GET /categories/{id}` и `GET /table/` за 365 дней.
- `app/categories/page.tsx` — **mod**: шапка карточки категории обёрнута в `Link` на `/categories/{id}`.
- `package.json` — **mod**: `recharts` (dependency), `@types/bun` (devDependency для типов bun:test).

Feedback loops: bun test 10/10 green, tsc --noEmit clean, eslint clean, next build green (route `/categories/[id]` собирается). Ручной smoke (две линии у Running Outdoor) не прогонялся — backend в сессии не поднят.

## 2026-07-22 — PHASE-01/16-checklist-upsert-today-page

Тикет: страница `/today` — checklist-категории как сетка чипсов (тап = toggle с оптимистичным обновлением через `PUT /entries/checklist`), form-категории — быстрый ввод числа первого числового поля (`POST /entries`). Затронуто 3 файла (1 new, 2 mod).

- `app/today/page.tsx` — **new**: секции по checklist-категориям с чипсами полей (состояние из entries за сегодня, оптимистичный toggle с откатом при ошибке); блок Quick input — строка на form-категорию с первым number-полем, input + кнопка сохранить.
- `lib/api.ts` — **mod**: `entriesAPI.upsertChecklist` (PUT `/entries/checklist`) и тип `ChecklistUpsert` (`values: Record<number, boolean>`).
- `components/Navigation.tsx` — **mod**: пункт Today (иконка Sun) между Dashboard и Categories.

Feedback loops: tsc --noEmit clean, eslint clean, next build green (route `/today` собирается).

## 2026-07-22 — PHASE-01/15-category-display-mode-group

Тикет: редактор категории — select «Display mode» (Form / Checklist) и текстовое поле «Group»; значения видны бейджами в карточке категории. Затронуто 2 файла (0 new, 2 mod).

- `lib/api.ts` — **mod**: тип `CategoryDisplayMode`, поля `display_mode`/`group` в `Category` и `CategoryCreate`.
- `app/categories/page.tsx` — **mod**: в форме добавлены select режима отображения и input группы (пустая группа отправляется как `null`); в карточке — бейджи режима и группы рядом со статусом Active/Inactive.

Feedback loops: tsc --noEmit clean, eslint clean, next build green.

Тикет: `PHASE-01/adhoc-lime-redesign` — редизайн всего web-фронтенда под дизайн-систему «Lime Tech» (`docs/PHASE-01/design/design-system.md`, референс `refs/ref.png`). Чисто презентационный рефакторинг: API-вызовы и data flow не менялись, `lib/api.ts` не тронут.

Затронуто файлов: 9 (mod 8, new 1).

- `app/globals.css` — mod. Токены палитры (CSS vars + Tailwind `@theme`), тёмная база, selection, тонкий скроллбар, keyframes (neon-spin, ring-draw, fade-rise).
- `app/layout.tsx` — mod. Тёмный shell `#090909`, Inter (next/font, был и раньше).
- `components/Navigation.tsx` — mod. Тёмный верхний nav, лаймовый активный pill, логотип с лаймовой точкой.
- `components/LoadingSpinner.tsx` — mod. Неоновое кольцо (SVG-дуга) вместо border-спиннера.
- `components/ErrorAlert.tsx` — mod. Тёмная поверхность, красный акцент, dismiss-кнопка.
- `app/page.tsx` — mod. Hero-карточка со счётом и прогресс-кольцом, KPI-ряд, recent activity, quick actions.
- `app/categories/page.tsx` — mod. Карточки с цветным icon-chip, тёмная модальная форма, лаймовый focus ring.
- `app/entries/page.tsx` — mod. Список с визуальной группировкой по датам, тёмные карточки и форма.
- `app/journal/page.tsx` — mod. Timeline-карточки с настроением и тегами-чипами, круглый mood picker в редакторе.
- `SESSION_REVIEW.md` — new. Этот файл.

Попутно: `catch (err: any)` заменён на `catch (err)` с narrowing через `instanceof Error` (запрет `any` по стандартам проекта); `as any` на field_type заменён на `as FieldCreate['field_type']`.

Feedback loop: `bun run build` (Next.js 16.1.6, Turbopack) — зелёный, TypeScript чистый.

## 2026-07-22 — PHASE-01/17-table-groups-sport-columns

Тикет: страница `/table` — вкладки по группам категорий, колонки = категории (значение primary-поля по дням), тап по ячейке открывает панель записей дня с редактированием/удалением. Затронуто 3 файла (1 new, 2 mod).

- `app/table/page.tsx` — **new**: вкладки-группы (категории без группы → вкладка Other, категории без полей скрыты), таблица за последние 14 дней (новые сверху), ячейка = агрегированное значение primary-поля; тап → модальная панель `DayEntriesPanel` (записи дня по категории, load через effect с cancellation-флагом + refresh-счётчик), `EntryEditor` — правка значений через `PATCH /entries/{id}` и удаление через `DELETE`; после сохранения таблица перезагружается.
- `lib/api.ts` — **mod**: `tableAPI.get(date_from, date_to)` и типы `TableResponse`/`TableCategoryMeta`/`TableDay`/`TableCell`.
- `components/Navigation.tsx` — **mod**: пункт Table (иконка Table2) между Today и Categories.

Feedback loops: tsc --noEmit clean, eslint clean (react-hooks/set-state-in-effect устранён рефакторингом effect), next build green (route `/table` собирается).

## 2026-07-22 — PHASE-01/18-table-checklist-columns-backfill

Тикет: вкладки checklist-групп на `/table` — колонки = boolean-поля checklist-категории, ячейка = галочка/пусто, тап по ячейке любого дня → toggle через PUT /entries/checklist (backfill задним числом) с оптимистичным обновлением и rollback при ошибке. Затронут 1 файл (0 new, 1 mod).

- `app/table/page.tsx` — **mod**: discriminated union `TableColumn` (`value` | `check`); `buildTabs` раскрывает checklist-категории в колонки по boolean-полям (сортировка по order), form-категории остаются колонкой primary-поля; параллельная загрузка `GET /table` + `GET /categories` (полные списки полей); `handleToggle` — оптимистичный `setCellChecked` (правка/вставка ячейки в состоянии TableResponse) + `PUT /entries/checklist`, откат и ErrorAlert при ошибке; check-ячейка — кнопка с `aria-pressed`, иконка Check при true.

Feedback loops: tsc --noEmit clean, eslint clean, next build green. Ручной smoke «снял галочку позавчера» — за пользователем (dev-стенд).

## 2026-07-22 — PHASE-01/24-ai-insights-endpoint-button

Тикет: кнопка «Разбор периода» на Dashboard. Затронуто 2 файла (0 new, 2 mod).

- `lib/api.ts` — **mod**: insightsAPI.create (POST /insights/, optional period_days) + интерфейс AIReport.
- `app/page.tsx` — **mod**: секция AI-разбора — discriminated union `InsightState` (idle/loading/error/ready), кнопка с disabled на время запроса, неоновый лоадер, `InsightMarkdown` (минимальный рендер ##/###/списков без новых зависимостей), ошибка (в т.ч. 503/502 с бэка) с кнопкой Retry.

Feedback loops: eslint clean, next build (включая TypeScript) green.

## 2026-07-22 — PHASE-01/21-chart-cumulative-mode

Тикет: режим Cumulative для графика категории. Затронуто 3 файла (2 new, 1 mod).

- `lib/chart-utils.ts` — **new**: чистая функция `cumulate(points)` — префиксные суммы по каждой серии независимо; null-пропуски остаются null и не ломают накопление; вход не мутируется.
- `lib/chart-utils.test.ts` — **new**: unit-тесты cumulate (пустой ряд, монотонный рост, пропуски дней, несколько линий, отсутствие мутации).
- `components/CategoryChart.tsx` — **mod**: переключатель «Per day | Cumulative» (aria-pressed), `cumulate` применяется после `sliceByPeriod` (накопление с начала выбранного периода); mode — отдельный useState, переживает смену периода.

Feedback loops: bun test 15/15 green, tsc --noEmit clean, eslint clean.

## 2026-07-22 — PHASE-01/22-category-page-entries-cards

Тикет: страница категории — под графиком вся история entries карточками по датам, редактирование и удаление на месте; после мутации график перестраивается; общий список Entries переведён на общий компонент. Затронуто 5 файлов (3 new, 2 mod).

- `lib/entry-groups.ts` — **new**: чистый хелпер `groupEntriesByDate` (извлечён из `app/entries/page.tsx`), сохраняет порядок дат и записей.
- `lib/entry-groups.test.ts` — **new**: unit-тесты группировки (пустой вход, порядок first-seen, состав групп).
- `components/EntryCard.tsx` — **new**: переиспользуемая карточка entry (извлечение из `app/entries/page.tsx`) + inline-редактирование (PATCH /entries/{id} с values/notes/date) и удаление (DELETE) внутри карточки; экспортирует `FieldValueInput` (type-aware input по field_type) и `entryInputClass` для форм.
- `app/entries/page.tsx` — **mod**: карточки заменены на `EntryCard` (delete-логика ушла в компонент), группировка через `groupEntriesByDate`, switch по field_type в EntryForm заменён на `FieldValueInput`.
- `app/categories/[id]/page.tsx` — **mod**: параллельная загрузка category + table + entries (limit 1000, пагинация out of scope); под графиком история entries по датам через `EntryCard`; `onMutated` инкрементирует refresh-счётчик — перезагружаются и entries, и данные графика.

Feedback loops: bun test 17/17 green, tsc --noEmit clean, eslint clean, next build green. Ручной smoke «поправил запись → линия перестроилась» — за пользователем (dev-стенд).

## 2026-07-22 — PHASE-01/23-checklist-bar-streaks

Тикет: страница checklist-категории — bar-график «X из N за день» вместо линий + текущий стрик по каждому boolean-полю. Затронуто 4 файла (0 new, 4 mod).

- `lib/chart-utils.ts` — **mod**: чистые функции `booleanFields` (boolean-поля в field order), `buildChecklistBarData` (число true-ячеек категории за день; missing/false = not done) и `currentStreak` (от today назад; день без true — разрыв; непроставленный today — pending и стрик не рвёт до конца дня).
- `lib/chart-utils.test.ts` — **mod**: unit-тесты bar-данных (пустая история, счёт по дням, чужие категории/поля/false) и стрика (0/1/N, разрыв, pending today, чужие поля).
- `lib/chart-data.ts` — **mod**: `sliceByPeriod` сделан generic `<T>` — переиспользуется для `ChecklistBarPoint[]` без изменения поведения.
- `components/CategoryChart.tsx` — **mod**: диспетчер по `display_mode` — для checklist рендерится `ChecklistCategoryChart` (BarChart done-per-day, Y domain 0..N, tooltip «X of N», лаймовые бейджи стриков по полям, лайн-переключатели периода); форма — прежний line chart; кнопки периода вынесены в общий `PeriodButtons`.

Feedback loops: bun test 27/27 green, tsc --noEmit clean, eslint clean, next build green.

## 2026-07-22 — PHASE-01/27-category-page-nav-and-quick-add

Тикет: страница категории — пейджер по категориям (стрелки + чипсы) и быстрое добавление записи в текущую категорию без ухода на Entries. Затронуто 5 файлов (3 new, 2 mod).

- `lib/category-nav.ts` — **new**: чистый хелпер `categorySiblings(categories, currentId)` — соседи по порядку списка. Без wrap-around: у первой нет prev, у последней нет next. Неизвестный id или пустой список дают `{prev: null, next: null}` — удалённая категория не должна молча пролистываться в соседнюю.
- `lib/category-nav.test.ts` — **new**: unit-тесты соседей (середина, края, единственный элемент, отсутствующий id, пустой список).
- `components/EntryForm.tsx` — **new**: модалка создания записи, извлечённая из `app/entries/page.tsx` без изменения поведения. Новый проп `lockedCategoryId` фиксирует категорию и прячет селектор — заголовок становится «New <Category> entry».
- `app/entries/page.tsx` — **mod**: локальный `EntryForm` удалён, страница подключает общий компонент; неиспользуемые импорты (`EntryCreate`, `EntryValueCreate`, `X`, алиас `inputClass`) убраны.
- `app/categories/[id]/page.tsx` — **mod**: в загрузку добавлен `categoriesAPI.getAll()`; в шапке — стрелки prev/next (`CategoryPagerButton`, на краях списка disabled-заглушка) и горизонтальный ряд чипсов всех категорий с `aria-current` на активной; кнопка «New entry» открывает `EntryForm` с `lockedCategoryId`, после успеха дёргает тот же refresh-счётчик, что и правки карточек — перечитываются entries и данные графика.

Feedback loops: bun test 33/33 green, tsc --noEmit clean, eslint clean, next build green. Визуальный smoke в браузере не выполнен — Chrome-расширение не подключено; проверка страницы за пользователем.

## 2026-07-22 — PHASE-01/27 round 2: разделение тикетов и review-маркеров

Файлов тронуто: 8 (0 new в коде, 2 new issue-файла, 6 mod).

- `app/categories/[id]/page.tsx` — **mod**: `categoriesAPI.getStreak(categoryId)` в общем `Promise.all` получил `.catch(() => null)`. Раньше падение вторичного виджета отклоняло весь батч и страница (график, история записей, заголовок категории) не рендерилась вовсе; теперь деградирует до «нет блока стрика».
- `next.config.ts` — **mod**: review-маркер `fix/mobile-api-base-url` (несуществующий тикет) заменён на `PHASE-01/30-lan-api-proxy-rewrite`.
- `lib/api.ts` — **mod**: маркер перечисляет оба тикета — файл несёт и streak-типы (#27), и относительный дефолт `API_BASE_URL` (#30).
- `components/EntryForm.tsx`, `lib/category-nav.ts`, `lib/category-nav.test.ts`, `app/entries/page.tsx`, `app/categories/[id]/page.tsx` — **mod**: маркеры перепривязаны с несуществующего `PHASE-01/27-category-page-nav-and-quick-add` на `PHASE-01/29-category-page-nav-and-quick-add`.
- `issues/PHASE-01/in-work/29-category-page-nav-and-quick-add.md` — **new**: пейджер по категориям + извлечённый `EntryForm` с `lockedCategoryId`. Номер 28 занят (`backlog/28-today-avoid-card.md`).
- `issues/PHASE-01/in-work/30-lan-api-proxy-rewrite.md` — **new**: LAN-доступ через Next-rewrite. Заведён отдельным тикетом, потому что это смена сетевой топологии: браузер → Next rewrite → backend, хост backend'а больше не попадает в бандл, Next становится звеном на горячем пути.

Feedback loops: bun test 37/37 green, `tsc --noEmit` clean, eslint clean, `next build` green (10 роутов). Визуальный smoke в браузере не выполнен.

## 2026-07-23 — PHASE-01/31 web quick-wins: MD-рендер, /entries?new=1 + FAB, checklist-фолбэк

Файлов тронуто: 9 (3 new, 5 mod, 1 deleted).

- `lib/markdown.ts` — **new**: чистый парсер markdown — заголовки `#`–`####`, маркированные (`-`/`*`) и нумерованные списки, инлайн-`**bold**` (незакрытый маркер остаётся текстом). Возвращает типизированные блоки, рендеринга не содержит.
- `lib/markdown.test.ts` — **new**: smoke-тесты парсера (уровни заголовков, оба вида списков, параграфы, bold в заголовке/пункте, незакрытый bold, несколько bold-подряд).
- `components/Markdown.tsx` — **new**: общий рендерер поверх `lib/markdown` — заменяет `InsightMarkdown`, стили сохранены (H1-H2 → lime h3, H3-H4 → h4, буллеты с lime-точкой), плюс нумерованные пункты и `<strong>` для bold.
- `components/InsightMarkdown.tsx` — **deleted**: вытеснен общим `Markdown`; bold там вообще не парсился.
- `app/page.tsx` — **mod**: Dashboard использует `Markdown`; все три ссылки «Log entry / Create first entry» ведут на `/entries?new=1` — форма открывается в 1 тап.
- `app/insights/page.tsx` — **mod**: история отчётов рендерится общим `Markdown`.
- `app/journal/page.tsx` — **mod**: контент записи рендерится через `Markdown` вместо plain `whitespace-pre-wrap`.
- `app/entries/page.tsx` — **mod**: `?new=1` открывает форму сразу (через `useSearchParams`, страница обёрнута в `Suspense`); добавлен FAB «+» fixed внизу справа — виден без скролла.
- `app/today/page.tsx` — **mod**: чипы чек-листа строятся только из boolean-полей; legacy-категория `checklist` без boolean-полей (кейс «Coffee») фолбэчит в quick number input.
- `app/categories/page.tsx` — **mod**: в редакторе под селектом Display mode подсказка, когда выбран checklist без boolean-поля (совпадает с новым API-правилом 422).

Feedback loops: bun test 44/44 green, `tsc --noEmit` clean, eslint clean, `next build` green (9 роутов). Визуальный smoke в браузере не выполнен.

## 2026-07-23 — PHASE-01/28 Today: карточка «N дней чистый» + форма срыва

Файлов тронуто: 6 (3 new, 3 mod).

- `lib/today-categories.ts` — **new**: чистая раскладка категорий Today на группы `avoid` / `checklist` / `quickForm`. Avoid-режим имеет приоритет (всегда streak-карточка, не quick-input); плюс перенесённые сюда хелперы `firstNumberField` / `booleanFields`.
- `lib/today-categories.test.ts` — **new**: тесты раскладки — avoid не попадает в quickForm, build-число остаётся quick-input, checklist с boolean → checklist, number-поле avoid-категории проброшено (или undefined, если его нет).
- `components/AvoidStreakCard.tsx` — **new**: карточка avoid-категории — крупный лаймовый бейдж «N days clean» + маленький best, кнопка «Happened» открывает инлайн-форму (сколько + заметка) → POST /entries → `onRelapse` перезагружает стрик.
- `lib/streak-format.ts` — **mod**: добавлен `formatCleanDays` (бейдж «N days clean» поверх `formatDays`).
- `lib/streak-format.test.ts` — **mod**: тесты `formatCleanDays` (0/1/42 дня).
- `app/today/page.tsx` — **mod**: раскладка через `partitionTodayCategories`; avoid-категории рендерятся секцией «Streaks» из `AvoidStreakCard`, стрики грузятся отдельно (деградация до «—» при ошибке) и перезагружаются после срыва; empty-state учитывает avoid.

Feedback loops: bun test 61/61 green, `tsc --noEmit` clean, eslint clean, `next build` green (10 роутов). Визуальный smoke в браузере не выполнен.

## 2026-07-23 — PHASE-01/35 category web UX + фикс update полей

Файлов тронуто: 2 (0 new, 2 mod).

- `lib/api.ts` — **mod**: `FieldCreate.id?: number` — при редактировании фронт возит `id` существующих полей, чтобы бэкенд обновлял их на месте (парный фикс к PHASE-01/35 backend, без него правки полей не сохранялись).
- `app/categories/page.tsx` — **mod**: (1) форма при редактировании кладёт `id` в поля; при создании стартует с одним пустым полем; сабмит переиндексирует `order` по позиции. (2) Кнопка «Add field» переехала вниз списка (широкая dashed-кнопка) — не нужно скроллить вверх при 20–30 полях. (3) Действия Cancel/Update вынесены в `sticky bottom-0` футер (submit через `form="category-form"`) — меньше скролла до кнопки на телефоне. (4) Переключатель вида карточки/список (segmented control, персист в `localStorage`); list-режим — компактные строки с цветной точкой, счётчиком полей и edit/delete справа, клик по строке ведёт на график.

Feedback loops: bun test 61/61 green, `tsc --noEmit` clean, eslint clean. `next build` не гонял локально (проверено в CI). Визуальный smoke в браузере не выполнен.

## 2026-07-24 — PHASE-01/40 каркас мобильного инстанса: тумблер, /m/ shell, таб-бар, манифест, Today

Файлов тронуто: 13 (10 new, 3 mod).

- `lib/view-mode.ts` — **new**: чистые хелперы вида. Маппинг `/<путь>` ↔ `/m/<путь>` по белому списку `MOBILE_ROUTES` (пока только `/today`), нормализация trailing slash, проверка границы префикса (`/markdown` не мобильный), чтение/запись предпочтения в storage с дефолтом `desktop` и no-op на сервере.
- `lib/view-mode.test.ts` — **new**: 27 тестов — обе стороны маппинга, идемпотентность, немаппящийся роут, `/m` → `/`, персист предпочтения и битое значение.
- `hooks/useToday.ts` — **new**: состояние экрана Today (загрузка категорий/записей/стриков, оптимистичный `toggleField` с откатом, `reloadStreak`, `nothingToTrack`), вынуто из `app/today/page.tsx` без изменения поведения; там же `todayISO` и `numberFieldSum`.
- `components/ViewToggle.tsx` — **new**: тумблер `Mobile` в десктопной навигации. Пишет предпочтение и роутит на парный путь; на роутах без мобильной версии задизейблен; на маунте возвращает пользователя в мобильный шелл, если предпочтение сохранено.
- `components/AppShell.tsx` — **new**: выбирает оболочку по пути — десктопная навигация + центрированный `main`, либо голые children, чтобы `app/m/layout.tsx` владел вьюпортом целиком.
- `components/QuickNumberRow.tsx` — **new**: строка быстрого числового ввода (текущая сумма + добавить), вынута из `app/today/page.tsx` и переиспользована мобильным экраном.
- `components/mobile/TabBar.tsx` — **new**: нижний таб-бар из пяти вкладок (`Today` и `Ещё` — мобильные, остальные ведут на десктопные роуты), тап-таргеты 44pt, safe-area снизу.
- `components/mobile/MoreSheet.tsx` — **new**: экран «Ещё» — `Journal` / `Table` / `Insights` и выход на десктопную версию (явно перезаписывает предпочтение, чтобы холодный старт не возвращал в мобильный шелл).
- `app/m/layout.tsx` — **new**: мобильный шелл — шапка с заголовком текущего экрана, скроллящийся контент, таб-бар; на маунте фиксирует предпочтение `mobile` (важно для запуска PWA сразу на `/m/today`).
- `app/m/today/page.tsx` — **new**: мобильный Today поверх `useToday` — одна колонка, чек-листы сеткой 2×N.
- `app/m/more/page.tsx`, `app/m/page.tsx` — **new**: роут «Ещё» и редирект `/m` → `/m/today`.
- `app/manifest.ts` — **new**: `display: standalone`, `start_url: /m/today`, `theme_color: #090909`, иконки 192/512. Иконки в `public/` — сгенерированные заглушки в лаймовой палитре, настоящие отдельным тикетом.
- `app/layout.tsx` — **mod**: экспорт `viewport` (`themeColor`, `viewportFit: cover`), ссылка на манифест, `apple-touch-icon`, `overflow-x-hidden` на body; шелл выбирается через `AppShell`.
- `components/Navigation.tsx` — **mod**: `ViewToggle` крайним справа за разделителем.
- `app/today/page.tsx` — **mod**: только разметка, всё состояние переехало в `useToday`; `QuickNumberRow` импортируется.

Feedback loops: bun test 88/88 green, `tsc --noEmit` clean, eslint clean, `next build` green (13 роутов, `/manifest.webmanifest` отдаётся). Визуальный smoke в браузере не выполнен.

## 2026-07-24 — PHASE-01/40 раунд 2: правки по ревью

Файлов тронуто: 26 (8 new, 18 mod).

**Новые модули**

- `lib/date.ts` / `lib/date.test.ts` — **new**: единственный `todayISO(now = new Date())` для строк `YYYY-MM-DD`; инъекция момента ради детерминированных тестов.
- `lib/today-entries.ts` / `lib/today-entries.test.ts` — **new**: чистое состояние экрана Today — `numberFieldSum`, `buildCheckedMap`, `isFieldChecked` / `setFieldChecked` (оптимистичный флип и откат — одна и та же функция, поэтому откат восстанавливает ровно прежнее значение) и `loadStreakMap` с деградацией упавшей категории до `null`.
- `lib/routes.ts` / `lib/routes.test.ts` — **new**: единый реестр экранов `{ id, name, href, icon, hasMobile, inTabBar }`; из него выводятся десктопная навигация, порядок таб-бара, список «More» и белый список мобильных роутов.
- `lib/ui-constants.ts` — **new**: `TAP_TARGET_PX = 44` в одном месте вместо трёх копий.
- `lib/theme.ts` — **new**: `THEME_COLOR` — токен, который читает ОС (манифест + `theme-color`), синхронизирован комментарием с `--color-background` в `globals.css`.

**Изменения**

- `lib/view-mode.ts` — **mod**: `MOBILE_ROUTES` выводится из реестра; добавлены `hasStoredViewMode` / `seedViewMode` (запись предпочтения только когда выбора ещё не было) и `toDesktopEntryPath` (десктопный близнец текущего экрана, дашборд — только для мобильных-онли экранов вроде `/m/more`).
- `lib/view-mode.test.ts` — **mod**: тесты на новые хелперы и на то, что `MOBILE_ROUTES` равен `hasMobile`-срезу реестра.
- `hooks/useToday.ts` — **mod**: чистые части вынесены в `lib/`, хук остался оркестрацией стейта.
- `app/m/layout.tsx` — **mod**: фикс back-button trap — `seedViewMode` вместо безусловной записи `mobile` на каждом монтировании.
- `components/ViewToggle.tsx` — **mod**: восстановление предпочтения теперь действительно только на холодном старте (ref-гард), иначе десктопный `/today` был недостижим из навигации; убрана недостижимая ветка `isMobilePath(pathname) ? 'desktop' : 'mobile'` — кнопка живёт только в десктопной навигации.
- `components/mobile/MoreSheet.tsx` — **mod**: выход на десктоп сохраняет экран (`toDesktopEntryPath`), ссылки берутся из реестра, строки UI на английском (`More`, `Desktop version`).
- `components/mobile/TabBar.tsx` — **mod**: вкладки выводятся из реестра, вкладка `Ещё` переименована в `More`.
- `components/Navigation.tsx` — **mod**: `navItems` = реестр.
- `components/QuickNumberRow.tsx`, `components/AvoidStreakCard.tsx`, `components/EntryForm.tsx`, `components/CategoryChart.tsx` — **mod**: общий `todayISO` из `lib/date`, приватные копии удалены; компоненты больше не импортируют хелперы из `@/hooks/useToday`.
- `app/today/page.tsx`, `app/m/today/page.tsx` — **mod**: `numberFieldSum` из `lib/today-entries`, `TAP_TARGET_PX` из `lib/ui-constants`.
- `app/manifest.ts`, `app/layout.tsx` — **mod**: `THEME_COLOR` переехал в `lib/theme`; root layout больше не импортирует из route-модуля.
- `app/categories/page.tsx` — **mod**: ключ `categoriesView` → `habit-tracker:categories-layout` + комментарий о разнице с `VIEW_MODE_STORAGE_KEY`.
- `app/globals.css` — **mod**: комментарий-якорь о синхронизации `--color-background` с `lib/theme.ts`.

Решение по языку UI: строки интерфейса — английские (остальной интерфейс английский); русский остаётся языком документации.

Не входит в слайс 40: `app/table/page.tsx` (маркер PHASE-01/36, refetch по `visibilitychange`/`focus`/`pageshow`) — коммитить отдельным коммитом. Сделано в раунде 7, коммит `5e16ee1`.

Feedback loops: bun test 127/127 green, `tsc --noEmit` clean, eslint clean, `next build` green (13 роутов). Визуальный smoke в браузере не выполнен.

## 2026-07-24 — PHASE-01/40 раунд 3: правки по ревью

Файлов тронуто: 15 (0 new, 15 mod).

**Дедупликация дат**

- `lib/date.ts` — **mod**: выделена базовая чистая `toISODate(d)`; `todayISO(now = new Date())` теперь просто `toISODate(now)`. Обе с докстрингами.
- `lib/date.test.ts` — **mod**: кейсы на `toISODate` с произвольными (не сегодняшними) датами — прошлое, однозначные месяц/день с zero-padding, високосное 29 февраля, отсутствие временной части.
- `lib/chart-data.ts` — **mod**: приватная копия `toISODate` удалена, импорт из `./date`.
- `app/journal/page.tsx` — **mod**: инлайн `new Date().toISOString().split('T')[0]` в форме журнала заменён на `todayISO()` из `@/lib/date`.

**Вход в мобильный шелл**

- `lib/view-mode.ts` — **mod**: добавлены `MOBILE_HOME` (выводится из `MOBILE_ROUTES`, т.е. из реестра, а не хардкод) и `mobileEntryPath(pathname)` — зеркало `toDesktopEntryPath`: мобильный близнец текущего экрана, иначе `MOBILE_HOME`. `MOBILE_PATH_PREFIX` переехал в `lib/routes.ts` и ре-экспортируется отсюда, чтобы реестр мог сам писать мобильные href без циклического импорта.
- `lib/view-mode.test.ts` — **mod**: покрытие `mobileEntryPath` (`/today` → `/m/today`, `/entries` → `/m/today`, `/` → `/m/today`, `/m/more` → `/m/today`, идемпотентность на `/m/today`, ни один роут реестра не уводит на десктоп) и `MOBILE_HOME`.
- `components/ViewToggle.tsx` — **mod**: кнопка больше не дизейблится на экранах без мобильного близнеца — пушит `mobileEntryPath(pathname)` и показывает title `Back to the mobile app`. `disabled` остался только на случай пустого `MOBILE_ROUTES` (в реестре нет ни одного мобильного экрана).

**Реестр как источник правды**

- `lib/routes.ts` — **mod**: `MOBILE_TABS` и тип `MobileTab` переехали сюда из компонента; добавлены `MOBILE_PATH_PREFIX`, `DEFAULT_SCREEN_TITLE` и `mobileScreenTitle(pathname)`; `MORE_PATH` собирается из префикса.
- `lib/routes.test.ts` — **mod**: тесты на состав и порядок `MOBILE_TABS` (мобильный близнец там, где он есть; десктопный роут там, где нет; `More` последним) и на `mobileScreenTitle`.
- `components/mobile/TabBar.tsx` — **mod**: остался чисто рендерящим — импортирует `MOBILE_TABS`, ничего не вычисляет.
- `app/m/layout.tsx` — **mod**: заголовок экрана берётся из `mobileScreenTitle` в `lib/routes`, локальная копия удалена; компонент таб-бара больше не источник данных.

**Мелкие**

- `app/today/page.tsx`, `app/m/today/page.tsx` — **mod**: инлайн `checked[category.id]?.[field.id] ?? false` заменён на `isFieldChecked` из `lib/today-entries`.
- `app/categories/page.tsx` — **mod**: локальный `type ViewMode = 'cards' | 'list'` переименован в `CategoryLayout` — имя `ViewMode` закреплено за оболочкой (`lib/view-mode`).

**Разделение коммитов**

- `app/table/page.tsx` — **mod**: файл несёт правки двух тикетов и коммитится ДВУМЯ коммитами. (1) PHASE-01/36 — refetch по `visibilitychange` / `focus` / `pageshow` (маркер в шапке файла — `PHASE-01/36`). (2) PHASE-01/40 — удаление приватной `toISODate` и импорт из `@/lib/date`. Смешивать их в одном коммите нельзя: слайс 40 не про инвалидацию кеша `/table`. Выполнено в раунде 7: `5e16ee1` и `a8d75ed`.

Feedback loops: bun test 146/146 green, `tsc --noEmit` clean, eslint clean, `next build` green (14 роутов, `/manifest.webmanifest` отдаётся). Визуальный smoke в браузере не выполнен.

### Раунд 4 — закрытие блокеров ревью (PHASE-01/40)

Правки по вердикту `issue-loop` (оба ревьюера дали REQUEST_CHANGES).

**Блокер 1 — чистота слоя `lib/`**

- `components/route-icons.ts` — **new**: карта `route id -> LucideIcon` + `routeIcon(id)`. Иконки уехали из реестра в UI-слой.
- `lib/routes.ts` — **mod**: убран импорт `lucide-react` и поле `icon` из `AppRoute` и `MobileTab`; `MobileTab` получил `id`; добавлен `MORE_ROUTE_ID`. Реестр стал чистыми данными и теперь безопасно импортируется из серверных модулей.
- `components/Navigation.tsx`, `components/mobile/TabBar.tsx`, `components/mobile/MoreSheet.tsx` — **mod**: иконка берётся через `routeIcon(id)`.
- `lib/routes.test.ts` — **mod**: тест на отсутствие `lucide-react` в исходнике реестра и на отсутствие поля `icon` у роутов.

**Блокер 2 — три источника правды для точки входа PWA**

- `app/manifest.ts` — **mod**: `start_url` читается из `MOBILE_HOME`, хардкод `/m/today` убран.
- `app/m/page.tsx` — **mod**: `redirect(MOBILE_HOME)` вместо `redirect('/m/today')`.
- `lib/view-mode.test.ts` — **mod**: тесты, что `manifest().start_url === MOBILE_HOME`, что редирект `/m` читает реестр, и что `MOBILE_HOME === mobileEntryPath(MOBILE_ROUTES[0])`.

**Блокер 3 — Module Map тикета**

- `issues/PHASE-01/in-work/40-...md` — **mod**: пути перекорневаны с `frontend/` на `habit-tracker/services/frontend/`, состав приведён в соответствие с фактически созданными модулями.

Feedback loops: bun test 152/152 green (было 146), `bunx tsc --noEmit` clean, `bun run lint` clean, `bun run build` green (14 роутов, `/manifest.webmanifest` отдаётся).

Не сделано: `git status` / `git diff` в этой среде висят и падают по таймауту (exit 143) — состояние дерева проверено напрямую по файлам и сборке, но не через git. Коммитов нет — сделаны в раунде 7 (`5e16ee1`, `a8d75ed`). Визуальный smoke на устройстве — тикет 49.

### Раунд 5 — верификация (PHASE-01/40)

Дата 2026-07-24. Правок кода нет: все acceptance тикета уже закрыты раундами 1-4, гэпов не найдено.

Проверено по acceptance: тумблер `Mobile` в `components/ViewToggle.tsx` пишет предпочтение и уводит на мобильного близнеца, обратный путь — `Desktop version` в `components/mobile/MoreSheet.tsx`, восстановление на холодном старте — эффект в `ViewToggle`. `/m/today` и `/today` делят `hooks/useToday.ts`. Таб-бар отдаёт пять вкладок из `MOBILE_TABS` с `minHeight/minWidth = TAP_TARGET_PX`. `app/manifest.ts` берёт `start_url` из `MOBILE_HOME`, `theme_color` и `viewport.themeColor` — из `lib/theme.ts`.

Feedback loops: `bun test` 152/152 green, `bunx tsc --noEmit` clean, `bun run lint` clean, `bun run build` green — 14 роутов, включая `/m`, `/m/today`, `/m/more`, `/manifest.webmanifest`.

Файлов тронуто: 1 — `SESSION_REVIEW.md` (**mod**, только эта запись). Маркеры `[review:need-review] PHASE-01/40-...` стоят во всех 20 файлах слайса.

### Раунд 6 — фикс блокеров ревью (PHASE-01/40)

Дата 2026-07-24. Файлов тронуто: 4 (0 new, 4 mod).

**Блокер 1 — restore-редирект срабатывал на каждом возврате с мобильного шелла**

- `components/ViewToggle.tsx` — **mod**: mount-scoped `useRef` заменён на session-scoped маркер в `sessionStorage`. `AppShell.tsx:12` не рендерит `Navigation`/`ViewToggle` под `/m/*`, поэтому ref обнулялся при каждом возврате на десктоп и `/today` мгновенно улетал обратно на `/m/today`. Маркер выставляется на первом прогоне эффекта в сессии независимо от того, случился ли редирект, — иначе переход `/entries` → `/today` считался бы холодным стартом.
- `lib/view-mode.ts` — **mod**: чистая функция `shouldRestoreMobile(pathname, mode, alreadyRestored)` плюс `VIEW_MODE_RESTORED_SESSION_KEY`, `hasRestoredViewMode`, `markViewModeRestored`, `browserSessionStorage`. Решение о редиректе стало тестируемым без рендера компонента.
- `lib/view-mode.test.ts` — **mod**: +10 тестов — холодный старт с `mode=mobile` даёт редирект; повторный вызов после restore в той же сессии его не даёт (регрессия на Back с `/m/today` на `/today`); `mode=desktop` не редиректит; маршрут без мобильного близнеца и уже-мобильный путь не редиректят; маркер переживает ремаунт компонента.

**Блокер 2 — владение `app/table/page.tsx`**

- `app/table/page.tsx` — **mod**: маркер в шапке перечисляет оба тикета — рефетч по `visibilitychange`/`focus`/`pageshow` принадлежит PHASE-01/36, импорт `toISODate` из `lib/date` — PHASE-01/40. Разделение на два коммита выполнено в раунде 7 (`5e16ee1`, `a8d75ed`), маркер сведён к одному тикету — `PHASE-01/36`.

Feedback loops: `bun test` 162/162 green (было 152), `bunx tsc --noEmit` clean, `bunx eslint .` clean, `bun run build` green — 14 роутов.

Не сделано (по условию задачи): коммиты не создавались, разделение рабочего дерева на слайсы 36/40 не выполнено; индекс git на момент правок уже был в синхроне (staged deletions отсутствуют, `git reset` не потребовался). Закрыто в раунде 7.

### Раунд 7 — разделение дерева на коммиты и закрытие хвостов ревью

Дата 2026-07-24. Файлов тронуто: 7 (2 new — тикеты в `issues/`, 5 mod).

**Разделение дерева на два коммита (шестой раунд подряд висело — закрыто)**

- `5e16ee1` `fix(categories): field sync matches id-less payloads by (name, type)` — слайс **PHASE-01/36**: `backend/app/crud/category.py` (сопоставление полей по id, затем по (имя, тип)), `backend/app/schemas/category.py` (докстринг `FieldUpsert`), `backend/tests/test_categories.py`, и из `frontend/app/table/page.tsx` — только шапка-маркер и эффект рефетча по `visibilitychange`/`focus`/`pageshow`. Частичный staging сделан не через `git add -p` (интерактивный режим в этой среде недоступен), а эквивалентно: `git diff` → выборка нужных ханков → `git apply --cached`. Версия файла в коммите самодостаточна — приватная `toISODate` в ней ещё на месте, сборка не ломается.
- `a8d75ed` `feat(mobile): mobile shell, tab bar, PWA manifest and mobile Today` — слайс **PHASE-01/40**: весь остальной фронт (36 файлов) — `app/m/*`, `app/manifest.ts`, `components/AppShell|ViewToggle|QuickNumberRow|route-icons`, `components/mobile/*`, `hooks/useToday.ts`, `lib/{routes,view-mode,date,today-entries,theme,ui-constants}` с тестами, иконки в `public/`, правки `app/layout.tsx`, `app/today/page.tsx`, `app/journal/page.tsx`, `app/categories/page.tsx`, `app/globals.css`, `components/{Navigation,EntryForm,CategoryChart,AvoidStreakCard}`, `lib/chart-data.ts` и оставшийся кусок `app/table/page.tsx` — удаление приватной `toISODate` и импорт из `@/lib/date`.
- Вне обоих коммитов намеренно оставлены незакоммиченными: оба `SESSION_REVIEW.md` (эта запись физически не может содержать собственный хеш), `brain-dumps/`, `.vscode/`. `issues/` в `.gitignore`.

**Правки по ревью**

- `app/table/page.tsx` — **mod**: маркер сведён к одному тикету `// [review:need-review] PHASE-01/36`, summary описывает только рефетч.
- `lib/date.ts` — **mod**: докстринг `toISODate` больше не утверждает, что «time and timezone offset dropped» — функция отдаёт календарную дату **в UTC**. Явно описан эффект: на UTC+3 запись в 01:30 локального времени уходит вчерашним днём. Переход на локальный календарь — тикет PHASE-01/56 (backlog).
- `lib/view-mode.ts` — **mod**: у `shouldRestoreMobile` зафиксирован принятый компромисс — сессионный маркер сжигается на первом прогоне эффекта, поэтому холодный старт на роуте без мобильного близнеца при `mode=mobile` оставляет пользователя на десктопе до конца сессии. Альтернатива возвращает петлю «каждый возврат на десктоп = холодный старт».
- `issues/PHASE-01/in-work/40-...md` — **mod**: в `## Decisions` добавлены два решения — расхождение с acceptance (односторонняя кнопка `Mobile` + обратный путь `Desktop version` в `/m/more` вместо двустороннего тумблера `Mobile on/off`) и сжигание сессионного маркера.
- `issues/PHASE-01/backlog/56-local-calendar-date-instead-of-utc.md`, `.../57-drop-field-identity-fallback.md` — **new**: follow-up тикеты на локальную дату и на снятие fallback-сопоставления по (имя, тип) после раскатки нового фронта на VPS.

Feedback loops: `bun test` 162/162 green, `bunx tsc --noEmit` clean, `bunx eslint .` clean, `bun run build` green (14 роутов). Бэкенд: `pytest` 148/148 green (через `TEST_DATABASE_URL` на проброшенный `localhost:5433` — дефолтный хост `postgres` резолвится только внутри compose-сети), `ruff check` clean, `mypy app` clean. Визуальный smoke на устройстве — тикет 49.

### Раунд 8 — закрытие блокеров дуального ревью (frontend-часть)

Дата 2026-07-24. Файлов тронуто: 6 (0 new, 6 mod). Правки внесены вручную в основной сессии, не сабагентом.

**Блокеры**

- Расщеплённый индекс — **закрыт**: весь слайс (`package.json`, `bun.lock`, `bunfig.toml`, `test-setup.ts`, `hooks/*`, `app/table/page.tsx`, `lib/chart-utils.ts`, `README.md`, backend `crud/category.py` + `tests/test_categories.py`, `bashs/review-status.sh`, `.gitignore`) приведён в одно состояние обычным `git add`. `git apply --cached` больше не применялся. `git diff --name-only` теперь показывает расхождение индекса и дерева только по двум `SESSION_REVIEW.md` и `brain-dumps/` — на сборку они не влияют, так что прогон loops по дереву эквивалентен прогону по индексу.
- Типы в staged-версии `hooks/useToday.test.ts` — **закрыт**: рабочее дерево уже несло исправленные фикстуры (`Category` без `icon: null`/`color: null`, `Entry` с `values`), в индекс они не попадали. После `git add` `bunx tsc --noEmit` чист.

**Правки**

- `hooks/useToday.ts` — **mod**: `loadData` вызывает `setError(null)` на успешном пути. Раньше баннер ошибки переживал любой последующий удачный silent-refetch — сеть восстановилась, а экран продолжал показывать «Failed to load today data».
- `hooks/useToday.test.ts` — **mod**: +1 тест «clears a stale error once a later fetch succeeds» (написан красным до фикса: падающий первый запрос → успешный refetch по `visibilitychange` → `error === null`).
- `hooks/useRefreshOnVisible.ts` — **mod**: снят guard `typeof document === 'undefined' || typeof window === 'undefined'`. React не выполняет `useEffect` при серверном рендере, поэтому ветка недостижима — мёртвый код.
- `hooks/useRefreshOnVisible.test.ts` — **mod**: удалён тест «renders on the server, where there is no document». Проверено эмпирически: `renderToStaticMarkup` не запускает эффекты, тест зелёный и с guard, и без него, то есть не проверял ничего. Удалены и осиротевшие импорты `createElement`/`renderToStaticMarkup`.
- `package.json` — **mod**: добавлен скрипт `"test": "bun test"`.
- `README.md` — **mod**: секция `### Tests` с `bun test` рядом с `bun dev`/`bun run build`.
- `bashs/review-status.sh` — **mod**: `git ls-files` исключает `.claude/` — три файла харнесса (`hooks/guard-clickup-task.sh`, `hooks/guard_clickup_task.py`, `workflows/issue-loop.js`) упоминают маркер прозой и держали счётчик выше нуля вечно. `need-review` упал со 183 до 180.

**Не сделано (осознанно, warning-уровень)**

- `Bun.sleep(400)` в `hooks/useRefreshOnVisible.test.ts` не заменён на инъектируемый источник времени: сид требует расширить публичную сигнатуру хука ради тестов, цена — 0.8 с на прогон.
- `mock.module('@/lib/api', ...)` в `hooks/useToday.test.ts` не локализован в `afterAll` — process-wide подмена покрывает 4 из 27 экспортов `lib/api.ts`.
- Тикет `51-stt-benchmark-on-vps.md` возвращён из `in-work/` в `backlog/` — работы по нему в дереве нет, он попал в `in-work` ошибочно.

Feedback loops: `bun test` 170/170 green, `bunx tsc --noEmit` clean, `bunx eslint .` clean, `bun run build` green.

### Тикет 41 — мобильный экран Entries + FullScreenSheet

Дата 2026-07-24. Ticket-id: `PHASE-01/41-mobile-entries-fullscreen-sheet`. Файлов тронуто: 11 (6 new, 5 mod).

**New**

- `components/mobile/FullScreenSheet.tsx` — обёртка редактора мобильного инстанса: бар «Cancel / заголовок / Done» над единственной скроллящейся областью. Два решения несут клавиатурное поведение и закреплены тестами: размер в `dvh` (не `vh`), поэтому при открытой клавиатуре лист ужимается до видимой области, и бар лежит вне `[data-sheet-scroll]`, поэтому прокрутка формы не уносит «Cancel»/«Done» за экран.
- `components/mobile/FullScreenSheet.test.tsx` — 8 тестов: действия бара, submit по Enter, busy-состояние (Done заблокирован, Cancel нет), и контракт вёрстки.
- `hooks/useEntries.ts` — состояние экрана Entries, вынутое из `app/entries/page.tsx`: список, категории, группировка по дате, фильтр по категории, `reload()` без спиннера, `categoryOf()`.
- `hooks/useEntries.test.ts` — 7 тестов: первичная загрузка со спиннером, группировка, рефетч при смене фильтра, проброс ошибки, тихий reload.
- `lib/entry-values.ts` + `lib/entry-values.test.ts` — чистые `draftValuesFromEntry` / `toEntryValues`, снявшие дублирование между `EntryForm`, `EntryCard` и мобильным листом.
- `app/m/entries/page.tsx` + `app/m/entries/page.test.tsx` — мобильный экран: список карточек, фильтр, FAB, создание и редактирование через лист, удаление с подтверждением. 6 интеграционных тестов гоняют весь путь через замоканный `lib/api`.

**Mod**

- `lib/routes.ts` — у экрана `entries` `hasMobile: true`. Из этого флага сами собой следуют белый список `MOBILE_ROUTES`, ссылка таба на `/m/entries` и заголовок шапки.
- `lib/routes.test.ts`, `lib/view-mode.test.ts` — маппинг `/entries` ↔ `/m/entries`; роль «экрана без мобильной версии» в тестах перешла к `/journal`.
- `lib/view-mode.ts` — обновлён пример в докblock `shouldRestoreMobile` (`/entries` → `/journal`).
- `app/entries/page.tsx` — переезд на `useEntries`; разметка прежняя, добавлен только `aria-label` на селект фильтра.
- `app/entries/page.test.tsx` — характеризационные тесты десктопной страницы, написанные до переезда и пройденные после.
- `components/EntryCard.tsx` — `FieldValueInput` принимает `id`, чтобы внешний `<label htmlFor>` называл контрол; конвертация draft ↔ payload делегирована `lib/entry-values`.

Feedback loops: `bun test` 208/208 green, `bunx tsc --noEmit` clean, `eslint` clean, `bun run build` green (15 роутов, среди них `/m/entries`).

### Тикет 41, раунд 2 — правки по ревью

Дата 2026-07-24. Ticket-id: `PHASE-01/41-mobile-entries-fullscreen-sheet`. Файлов тронуто: 11 (2 new, 9 mod).

**New**

- `hooks/useEntryDraft.ts` — единственный владелец черновика записи (категория, дата, заметки, значения) и его сохранения. `save()` сам выбирает `entriesAPI.create` против `entriesAPI.update` по наличию редактируемой записи, поэтому три редактора — десктопная модалка, инлайн-редактор карточки и мобильный лист — свелись к разметке и отдают один текст ошибки (`SAVE_ENTRY_ERROR`) вместо трёх разных. Флаг `saving` снимается до вызова `onSaved()`, а не после: `onSaved` обычно размонтирует редактор.
- `hooks/useEntryDraft.test.ts` — 12 тестов: сидирование из записи, сброс значений при смене категории, create против update, отказ сохранять без категории, единый текст ошибки, busy-состояние.

**Mod**

- `components/mobile/FullScreenSheet.tsx` — проп `error` + `onDismissError`: баннер рендерится первым элементом внутри `[data-sheet-scroll]`. Раньше ошибка сохранения уходила в page-level баннер, полностью закрытый листом, — «Готово» на вид не делало ничего. Закрыт и контракт `role="dialog" aria-modal="true"`: Escape зовёт `onCancel`, фокус при открытии уходит на первое поле формы (не на «Cancel» — это приглашение выбросить черновик), Tab/Shift+Tab заворачиваются по краям, скролл `body` заморожен на время открытия.
- `components/mobile/FullScreenSheet.test.tsx` — +8 тестов: баннер внутри листа и первым, dismiss, Escape, начальный фокус, обе стороны ловушки фокуса, заморозка/разморозка `body`.
- `app/m/entries/page.tsx` — редактор переведён на `useEntryDraft`, ошибка сохранения живёт в листе, page-level баннер остался только для загрузки списка и удаления. Пустой список категорий больше не открывает лист с `category_id: 0` и селектом без опций — вместо этого экран «Create a category first» со ссылкой на `/categories` и без FAB. Заголовок листа (`Log an entry`) разведён с `aria-label` FAB (`New entry`): кнопка и диалог с одним именем — два неразличимых узла в дереве доступности. Резолв `field_id -> field.name` заменён на `labelledValues`.
- `app/m/entries/page.test.tsx` — тест отказа сохранения теперь утверждает видимость (`closest('[role="dialog"]')`), а не только наличие текста; +1 тест на пустой список категорий.
- `hooks/useEntries.ts` — `useRefreshOnVisible(reload)` по аналогии с `useToday`: в standalone-PWA документ не перезагружается, и возврат на `/m/entries` показывал список, забранный при запуске приложения. `grouped` завёрнут в `useMemo` по `entries` — публичный контракт хука больше не выдаёт новый массив на каждый рендер.
- `hooks/useEntries.test.ts` — +2 теста: стабильность идентичности `grouped` и тихий рефетч по `visibilitychange`.
- `components/EntryCard.tsx` — инлайн-редактор вынесен в `EntryEditForm` на `useEntryDraft` (монтируется только на время правки, поэтому черновик сидируется из актуальной записи и не переживает reload списка); сетка значений перешла на `labelledValues`; `entryInputClass` больше не живёт здесь.
- `components/EntryForm.tsx` — собственная копия конверсии `fields.map(...)` и весь draft-стейт заменены на `useEntryDraft`; ушёл импорт `EntryValueCreate`.
- `lib/entry-values.ts` — добавлена `labelledValues(category, entry)`: третья копия резолва `field_id -> имя поля` в разметке убрана, поле без имени (удалено из категории) получает `UNNAMED_FIELD_LABEL` вместо пустого заголовка. Header-summary приведён к фактическим потребителям.
- `lib/ui-constants.ts` — сюда переехал `entryInputClass`: им пользуются все три редактора, и импорт стиля из компонента делал `EntryCard` де-факто стилевым модулем для остальных.

Backend: `uv run pytest tests/test_categories.py` прогнан с поднятым `habit_postgres` (порт 5433, база `habit_tracker_test`) — 30 passed, в том числе `test_dropping_a_field_with_history_is_logged`, остававшийся с прошлой сессии неверифицированным.

Feedback loops: `bun test` 235/235 green, `bunx tsc --noEmit` clean, `eslint` clean, `bun run build` green (15 роутов).

### Тикет 41, раунд 3 — правки по ревью

Дата 2026-07-24. Ticket-id: `PHASE-01/41-mobile-entries-fullscreen-sheet`. Файлов тронуто: 8 (2 new, 6 mod).

**New**

- `components/FieldValueInput.tsx` — `FieldValueInput` и `DurationInput`, вынесенные из `EntryCard.tsx`. Мобильный шелл импортировал инпут из десктопной карточки, то есть тянул за собой весь `EntryCard` ради одного контрола; мотивация та же, что у переезда `entryInputClass` в `lib/ui-constants.ts`.
- `components/ViewToggle.test.tsx` — 3 теста на cold-start restore: редирект на мобильного близнеца, сохранение query string, отсутствие редиректа при `desktop` в хранилище.

**Mod**

- `app/m/entries/page.tsx` — читает `useSearchParams()` внутри `Suspense`-границы (как `app/entries/page.tsx`) и при `?new=1` инициализирует лист как `{ kind: 'create' }`, поэтому deep-link «+» открывает редактор с первого кадра. Импорт `FieldValueInput` переведён на новый модуль, `NEW_ENTRY_SHEET_TITLE` экспортирован для теста.
- `app/m/entries/page.test.tsx` — +2 теста: `?new=1` открывает лист с заголовком создания, без параметра лист закрыт.
- `components/ViewToggle.tsx` — cold-start restore приклеивает query string к `resolvePath(pathname, 'mobile')`. Без этого `/entries?new=1` при подмене на `/m/entries` терял параметр, и половина deep-link'а («открой редактор») пропадала до того, как экран успевал его прочитать. Сам эффект выделен в `MobileRestore` под собственной `Suspense`-границей: компонент монтируется layout'ом, вне границы любой страницы, и `useSearchParams` без обёртки ронял пререндер всех роутов (`bun run build` это и поймал).
- `hooks/useEntries.ts` — успешная загрузка гасит только ошибку загрузки: состояние ошибки хранит происхождение (`fromLoad`), `setError` из экрана помечается как внешняя. Раньше тихий рефетч по `useRefreshOnVisible` стирал ошибку удаления ровно в тот момент, когда пользователь возвращался её прочитать.
- `hooks/useEntries.test.ts` — +2 теста: внешняя ошибка переживает тихий рефетч, ошибка загрузки гаснет после успешного `reload`.
- `components/EntryCard.tsx`, `components/EntryForm.tsx` — импортируют `FieldValueInput` из нового модуля; из карточки ушли `DurationInput` и импорты `lib/duration`.

Feedback loops: `bun test` 242/242 green, `bunx tsc --noEmit` clean, `eslint` clean.

### Тикет 41, раунд 4 — закрытие блокеров дуального ревью

Дата 2026-07-24. Файлов тронуто: 10 (0 new, 10 mod). Правки внесены вручную в основной сессии.

**Реальный дефект корректности — двойной сабмит (закрыт на двух уровнях)**

- `components/mobile/FullScreenSheet.tsx` — **mod**: `handleSubmit` выходит рано при `busy`. Задизейбленная кнопка Done закрывала только клик; Enter (и «Go» на мобильной клавиатуре) сабмитит форму напрямую, минуя кнопку, и создавал вторую запись.
- `hooks/useEntryDraft.ts` — **mod**: добавлен `savingRef`, проверяемый до `setSaving(true)` и сбрасываемый на обоих выходах. `saving` — это state, и для второго вызова в том же тике он всё ещё читается false.
- `components/mobile/FullScreenSheet.test.tsx` — **mod**: тест «blocks a second submit while the first is in flight» переписан — теперь реально сабмитит форму при `busy: true` и проверяет, что `onDone` не вызван. Прежняя версия проверяла только атрибут `disabled` и оставалась зелёной при отсутствующей гарантии.
- `hooks/useEntryDraft.test.ts` — **mod**: +1 тест «ignores a second save fired before the first one settles» — два `save()` в одном `act`, ожидается ровно один `create`. Оба теста написаны красными до фиксов.

**Хрупкие контракты**

- `lib/routes.ts` — **mod**: контракт deep-link переехал в реестр — `NEW_ENTRY_PARAM`, `NEW_ENTRY_VALUE`, `NEW_ENTRY_QUERY` и предикат `wantsNewEntry(params)`. Литерал `?new=1` был продублирован в четырёх несвязанных местах.
- `app/entries/page.tsx`, `app/m/entries/page.tsx` — **mod**: оба читают параметр через `wantsNewEntry`, локальные копии констант удалены.
- `app/page.tsx` — **mod**: три ссылки «Log entry» собираются из `NEW_ENTRY_QUERY`.
- `lib/ui-constants.ts`, `app/m/entries/page.tsx`, `app/m/entries/page.test.tsx` — **mod**: `NEW_ENTRY_SHEET_TITLE` переехал из route-файла в `ui-constants`; произвольные именованные экспорты из App-Router `page.tsx` — контракт, который Next не обещает держать. Тест импортирует константу оттуда же.
- `components/FieldValueInput.tsx` — **mod**: снят `export default` — все три потребителя импортируют именованный экспорт.

Feedback loops: `bun test` 243/243 green, `bunx tsc --noEmit` clean, `bunx eslint .` clean, `bun run build` green (15 роутов).

Побочные изменения десктопа, чтобы ревью их не переоткрывало: `/entries` теперь рефетчится по `visibilitychange`/`focus`/`pageshow` (через `useRefreshOnVisible` в `useEntries`), и текст ошибки создания в модалке сменился с «Failed to create entry» на общий `SAVE_ENTRY_ERROR` («Failed to save entry»).

### Тикет 42 — мобильные экраны Categories и Category detail

Дата 2026-07-24. Файлов тронуто: 18 (8 new, 10 mod).

**Вложенные роуты в реестре экранов**

- `lib/routes.ts` — **mod**: у `AppRoute` появился флаг `hasMobileNested` («мобильный экран обслуживает и вложенные пути»), у Categories выставлены `hasMobile: true` + `hasMobileNested: true`. `MobileTab` несёт тот же признак, `mobileScreenTitle` продолжает называть экран на `/m/categories/12` вместо отката к имени приложения.
- `lib/view-mode.ts` — **mod**: приватный `mobileRouteFor` резолвит либо точный whitelisted роут, либо родителя-владельца вложенных путей. На нём переписаны `hasMobileVersion`, `toMobilePath` и `toDesktopEntryPath` — последний больше не выбрасывает id и не отправляет читателя `/m/categories/12` на дашборд.
- `components/mobile/TabBar.tsx` — **mod**: таб остаётся подсвеченным на своих вложенных роутах.
- `lib/routes.test.ts`, `lib/view-mode.test.ts` — **mod**: +18 тестов на вложенный роут с параметром, включая негативные (`/today/12` не считается мобильным).

**Вынос логики в хуки**

- `hooks/useCategories.ts` — **new**: список (грузится с `active_only=false`), персистентная раскладка cards/list, удаление с сообщением об отказе. Рядом `useCategoryDraft` — единственный владелец формы категории и её сохранения; id полей уезжают в payload, поэтому бэкенд диффает поля на месте, а не заменяет их вместе с историей значений.
- `hooks/useCategoryDetail.ts` — **new**: один батч-запрос (категория, соседи, дни графика, записи, streak), группировка записей по датам, guard на нечисловой id. Возвращает дискриминированное объединение по `loaded`, чтобы экраны один раз проверили флаг и дальше получали данные не-null.
- `app/categories/page.tsx`, `app/categories/[id]/page.tsx` — **mod**: переведены на хуки, разметка сохранена (переключатель карточки/список, sticky-футер модалки, пейджер, quick-add). Дополнительно `grid-cols-2` в модалке стал `grid-cols-1 sm:grid-cols-2` — на узком экране пары контролов больше нет.
- `hooks/useCategories.test.ts`, `hooks/useCategoryDetail.test.ts` — **new**: 25 тестов.

**Мобильные экраны**

- `app/m/categories/page.tsx` — **new**: список категорий, редактирование в `FullScreenSheet`, каждый контрол формы на своей строке, карточка поля стопкой (имя, тип, опции, required, remove).
- `app/m/categories/[id]/page.tsx` — **new**: детальный экран; полоса категорий — `nav` с `overflow-x-auto` и пилюлями `whitespace-nowrap shrink-0`, поэтому она скроллится внутри себя, а не растягивает body. Quick-add — тот же лист, но без пикера категории: роут её уже зафиксировал.
- `lib/ui-constants.ts` — **mod**: `NEW_CATEGORY_SHEET_TITLE`.
- `app/m/categories/page.test.tsx`, `app/m/categories/[id]/page.test.tsx` — **new**: 23 теста, включая проверку «в листе нет ни одного `grid-cols-2`».

**Тестовая инфраструктура**

`mock.module` в bun фиксирует набор *имён* экспорта модуля при первой линковке и делит реестр на весь прогон, поэтому частичный мок `@/lib/api` в одном файле удалял `tableAPI` для всех остальных. Все шесть моков `@/lib/api` и четыре мока `next/navigation` приведены к полной поверхности (`hooks/useEntries.test.ts`, `hooks/useEntryDraft.test.ts`, `hooks/useToday.test.ts`, `app/entries/page.test.tsx`, `app/m/entries/page.test.tsx`, `components/ViewToggle.test.tsx` — **mod**).

Feedback loops: `bun test` 308/308 green, `bunx tsc --noEmit` clean, `eslint` clean, `bun run build` green (17 роутов).

### Тикет 42 — раунд 2 (правки по ревью)

Дата 2026-07-24. Файлов тронуто: 12 (2 new, 10 mod).

**Дедупликация редактора записи**

- `components/mobile/EntryEditorSheet.tsx` — **new**: единственный мобильный редактор записи. Пропсы `{ categories, entry?, lockedCategory?, onCancel, onSaved }`; пикер категории рендерится только когда выбор реально есть — не при редактировании и не при зафиксированной роутом категории.
- `app/m/entries/page.tsx`, `app/m/categories/[id]/page.tsx` — **mod**: локальные `EntryEditorSheet` и `QuickAddSheet` удалены, оба экрана монтируют общий компонент. Тесты обеих страниц гоняют его же; в `app/m/entries/page.test.tsx` добавлена проверка, что при редактировании пикера категории нет.

**Общие константы**

- `lib/ui-constants.ts` — **mod**: `DISPLAY_MODE_LABELS`, `STREAK_MODE_LABELS`, `FIELD_TYPE_LABELS` (типизирован как `Record<FieldCreate['field_type'], string>`) и `compactInputClass` — плотный вариант поля для строк полей десктопной модалки.
- `app/categories/page.tsx`, `app/m/categories/page.tsx` — **mod**: локальные копии лейблов и локальный `inputClass` удалены. Десктопный `FieldRow` рендерит `<option>` из `Object.entries(FIELD_TYPE_LABELS)`, поэтому новый тип поля в API-типе больше не может потеряться в рукописном списке.

**Баннер ошибки не переживает успешную загрузку**

- `hooks/useCategories.ts`, `hooks/useCategoryDetail.ts` — **mod**: `setError(null)` в начале `load`. Плюс два теста в `hooks/useCategories.test.ts` и один в `hooks/useCategoryDetail.test.ts` (навигация по стрипу категорий).

**Глубина вложенности и единый предикат**

- `lib/view-mode.ts` — **mod**: вместо `startsWith(parent + '/')` матчится ровно один дополнительный сегмент, так что `/categories/12/anything` мобильной версии не имеет. `lib/view-mode.test.ts` — **mod**: два теста на трёхсегментный путь.
- `lib/routes.ts` — **mod**: предикат `isNestedMobileRoute` экспортируется и используется и для `MobileTab.nested`, и для сборки `NESTED_MOBILE_ROUTES`.

**Характеризационный тест десктопа**

- `app/categories/page.test.tsx` — **new**: 6 тестов — переключатель карточки/список с персистом, открытие/закрытие модалки редактирования, submit из sticky-футера через `form="category-form"` (кнопка вне формы), удаление только после подтверждения.

Feedback loops: `bun test` 319/319 green, `bunx tsc --noEmit` clean, `eslint` clean.

`bun run build` (прод-сборка, догнан в раунде 3): green, 16 роутов — `/m/categories` статический, `/m/categories/[id]` и `/categories/[id]` динамические. Оба новых роута с `useParams` собираются без ошибок пререндера.

### Тикет 42 — раунд 3 (правки по ревью)

Дата 2026-07-24. Файлов тронуто: 6 (0 new, 6 mod).

**Empty-state Entries больше не выкидывает из мобильной оболочки**

- `app/m/entries/page.tsx` — **mod**: `CATEGORIES_HREF` собирается из `MOBILE_PATH_PREFIX` и указывает на `/m/categories`. Прежний литерал `/categories` уводил на десктопный экран, откуда `MobileRestore` уже не возвращает: редирект в `/m` он делает один раз за сессию.
- `app/m/entries/page.test.tsx` — **mod**: тест empty-state теперь требует ровно `/m/categories` (до фикса падал на `/categories`).

**Соседи в стрипе и пейджере совпадают со списком**

- `hooks/useCategoryDetail.ts` — **mod**: `categoriesAPI.getAll(false)` вместо дефолтного active-only — тот же источник, что у `/m/categories` и `/categories`. Неактивная категория, открытая из списка, снова видит себя в собственной таб-полосе и получает живые prev/next.
- `hooks/useCategoryDetail.test.ts` — **mod**: мок `categoriesAPI.getAll` пробрасывает аргумент, добавлен тест на вызов с `false`.

**Цвет категории по умолчанию — одна константа**

- `lib/ui-constants.ts` — **mod**: `DEFAULT_CATEGORY_COLOR` переехал сюда к остальным кросс-шелловым UI-константам.
- `hooks/useCategories.ts` — **mod**: импортирует и ре-экспортирует её, поэтому обе страницы категорий свои импорты не меняли.
- `components/EntryCard.tsx` — **mod**: приватная копия `'#B8FF36'` удалена, значение берётся из `lib/ui-constants`.

Feedback loops: `bun test` 320/320 green, `bunx tsc --noEmit` clean, `bun run lint` (eslint) clean, `bun run build` green (16 роутов).

**Разделение рабочего дерева по тикетам (коммиты в этой сессии не делались)**

Вне слайса 42 и коммитятся отдельным коммитом: `backend/app/crud/category.py` вместе с `backend/tests/test_categories.py` (маркер `[review:need-review] PHASE-01/36-category-update-history-loss`), а также инфраструктура тестового прогона и ревью-счётчика — `bashs/review-status.sh`, `habit-tracker/services/frontend/bunfig.toml`, `habit-tracker/services/frontend/test-setup.ts`, `.gitignore`. Слайс 42 — только `lib/`, `hooks/`, `app/categories/`, `app/m/`, `components/mobile/`, `components/EntryCard.tsx`.

### Тикет 43 — мобильный Dashboard (/m) + hero-кольцо, раунд 2

Дата 2026-07-24. Ticket-id `PHASE-01/43-mobile-dashboard`. Файлов тронуто: 9 (2 new, 7 mod).

**Новые модули**

- `hooks/useDashboard.ts` — **new**: состояние Dashboard, вынутое из `app/page.tsx`, — параллельная загрузка категорий/записей/журнала, `computeDashboardStats`, поток AI-разбора (`INSIGHT_PERIOD_OPTIONS`, discriminated union состояния). Десктопная страница и `/m` делят один хук, поэтому карточки и лента не расходятся.
- `components/ProgressRing.tsx` — **new**: общий hero-виджет прогресс-кольца (лаймовая дуга поверх бледного трека), параметр `size` — десктоп и мобильный шелл рендерят один компонент разного диаметра.

**Изменения**

- `app/page.tsx` — **mod**: десктопный Dashboard переведён на `useDashboard` и `ProgressRing`; поведение прежнее.
- `app/m/page.tsx` — **mod**: голый `/m` стал мобильным Dashboard (близнец `/`) поверх `useDashboard`, одна колонка без горизонтального скролла; раньше `/m` был `redirect` на `/m/today`.
- `app/manifest.ts` — **mod**: `start_url`/точка входа PWA — мобильный Dashboard (`/m`); маркер и summary дополнены тикетом 43.
- `lib/routes.ts` — **mod**: у Dashboard `hasMobile: true`; `MOBILE_TABS` маппит корневой `/` на голый `/m` (без хвостового слэша — `/m/` не маппится ни на один роут).
- `lib/routes.test.ts` — **mod**: тест таб-бара обновлён — вкладка Dashboard ведёт на `/m`, а не на десктопный корень.
- `lib/view-mode.ts` — **mod**: `toMobilePath('/')` → `/m` (краевой случай пустого хвоста), `MOBILE_HOME` выводится через `toMobilePath`.
- `lib/view-mode.test.ts` — **mod**: покрытие маппинга корня `/` ↔ `/m` (идемпотентность, round-trip, `resolvePath`, `mobileEntryPath`).

**Разделение диффа (round 2 review)**

Вся LLM-CLI/инфра-обвязка, по ошибке замешанная в рабочее дерево слайса 43, вынесена в отдельный тикет `issues/PHASE-01/backlog/58-llm-cli-insights-infra.md`: `habit-tracker/services/backend/Dockerfile` (Node 22 + `@anthropic-ai/claude-code`), `habit-tracker/docker-compose.yml` и `deploy/docker-compose.prod.yml` (env `LLM_BACKEND`/токены, mount `~/.claude`, gunicorn `--timeout` 60→180), `deploy/README.md`. Готовый дифф — `issues/PHASE-01/backlog/58-llm-cli-insights-infra.patch`; сами файлы откачены к HEAD (`git restore`). Регрессия деплой-степа `.github/workflows/ci.yml` (голый `git pull `, потерянный `cd habit-tracker`, хвостовой пробел) тоже откачена к HEAD, где deploy-step уже корректен (`cd habit-tracker` + `git pull origin main` + `make up`). Рабочее дерево слайса 43 — только frontend-файлы выше.

Acceptance-критерий про читаемость `CategoryChart` на телефоне снят как устаревший: графики живут на страницах категорий, ни `/` ни `/m` их не рендерят (правка в тикете).

Feedback loops: `bun test lib/` 204/204 green, `tsc --noEmit` clean, `bun run lint` (eslint) clean, `bun run build` green (16 роутов, включая `/m` и `/manifest.webmanifest`). Коммиты в этой сессии не делались, issue не двигался.

---

Дата 2026-07-24. Ticket-id `PHASE-01/44-mobile-journal`. Файлов тронуто: 7 (2 new, 5 mod).

**Новые модули**

- `hooks/useJournal.ts` — **new**: состояние экрана Journal, вынутое из `app/journal/page.tsx`, — загрузка списка (spinner только на первой), `error`/`setError` с различением load-ошибки и ошибки экрана, `reload`, тихий рефетч на `visibilitychange` через `useRefreshOnVisible`. Десктоп и `/m/journal` делят один хук. Зеркалит проверенный `useEntries`.
- `app/m/journal/page.tsx` — **new**: мобильный экран Journal — тот же список через `useJournal`, MD через общий `components/Markdown.tsx`, создание/редактирование в `FullScreenSheet` (инлайновый `JournalEditorSheet` с полями title/date/mood/content/tags), FAB, delete с confirm. Весь читаемый текст не мельче `text-sm`.

**Изменения**

- `components/journal-moods.ts` — **new**: общий реестр настроений (value/label/icon/color) + `moodOption(...)`, чтобы настроение рендерилось одинаково в обоих шеллах; убирает дублирование `MOOD_OPTIONS`.
- `app/journal/page.tsx` — **mod**: десктопный Journal переведён на `useJournal`; `MOOD_OPTIONS` теперь импортируется из `components/journal-moods`; поведение прежнее.
- `lib/routes.ts` — **mod**: у Journal `hasMobile: true` (попадает в whitelist `MOBILE_ROUTES`, остаётся под «Ещё» — `inTabBar: null`); добавлен экспорт-хелпер `mobileHref(route)`, переиспользован в `MOBILE_TABS`; `mobileScreenTitle` теперь именует и не-таб мобильные экраны (шапка `/m/journal` → «Journal»).
- `lib/routes.test.ts` — **mod**: тест на `mobileScreenTitle('/m/journal')` → «Journal».
- `lib/view-mode.test.ts` — **mod**: journal переведён в положительные кейсы (mobile twin `/m/journal`, whitelist, cold-start redirect), роль «нет мобильной версии» отдана `/insights`.
- `components/mobile/MoreSheet.tsx` — **mod**: ссылка на экран из «Ещё» с мобильной версией ведёт на `/m`-близнец (`toMobilePath(route.href) ?? route.href`) — Journal открывается мобильным, а Table/Insights остаются десктопными до своих слайсов.

**Заметка про тесты хука**

Юнит-тест `hooks/useJournal.test.ts` был написан и прогнан red→green в изоляции, но снят из дерева: полный `bun test` делит один глобальный `mock.module('@/lib/api')`, и все существующие 10 mock-фабрик не объявляют `journalAPI` (первым линкуется `useEntries.test`, замораживая namespace без journal). Добавить journal во все фабрики — правка 10 чужих тест-файлов вне границы тикета (`Test boundary: lib/`). Хук — точная копия покрытого тестами `useEntries`, покрыт typecheck и общими lib-тестами роутинга.

Feedback loops: `bun test` (весь фронт) 332/332 green, `tsc --noEmit` exit 0, `eslint` exit 0. Коммиты не делались, issue не двигался.

---

## 2026-07-25 — PHASE-01/46-mobile-insights

Финальный слайс мобильного порта: у Insights появляется `/m`-версия, whitelist покрывает все экраны реестра.

**Новые модули**

- `hooks/useInsights.ts` — **new**: состояние экрана Insights, вынутое из `app/insights/page.tsx` — список отчётов (`reports`, `loading`, `error`/`setError`), `ReportView` (закрыт/грузится/ошибка/открыт), `openReport` (второй тап по открытому сворачивает), `reload`. Плюс экспорт чистого `formatReportDate` — единый форматтер даты для обоих шеллов.
- `app/m/insights/page.tsx` — **new**: мобильный Insights — тот же список через `useInsights`, одна колонка карточек, разворачивающихся в отчёт с MD через `components/Markdown.tsx`; кнопка «Запустить разбор» шириной в экран + выбор периода (7/30/90) из `INSIGHT_PERIOD_OPTIONS`; после генерации список перечитывается и новый отчёт сразу открывается. Весь читаемый текст не мельче `text-sm`.

**Изменения**

- `app/insights/page.tsx` — **mod**: десктопный Insights переведён на `useInsights` (список/открытие/reload), локальный `formatDate` заменён на `formatReportDate`; разметка прежняя.
- `lib/routes.ts` — **mod**: у Insights `hasMobile: true` (попадает в whitelist `MOBILE_ROUTES`, остаётся под «Ещё» — `inTabBar: null`); шапка `/m/insights` → «Insights» через существующий `mobileScreenTitle`.
- `lib/view-mode.ts` — **mod**: только комментарии — insights больше не «пример без мобильной версии»; логика без изменений.
- `lib/view-mode.test.ts` — **mod**: insights переведён в положительные кейсы (mobile twin `/m/insights`, whitelist, cold-start redirect, resolvePath в обе стороны); роль «нет мобильной версии» отдана вложенному роуту плоского экрана `/today/12`; добавлен тест «реестр покрыт целиком» — `MOBILE_ROUTES` равен всем `APP_ROUTES.href`.

`components/mobile/MoreSheet.tsx` не менялся: ссылка на Insights ведёт на `/m/insights` автоматически через `toMobilePath(route.href) ?? route.href`, как только у экрана `hasMobile: true`.

Feedback loops: `bun test` (весь фронт) 338/338 green, `tsc --noEmit` exit 0, `eslint` exit 0. Коммиты не делались, issue не двигался.

### Тикет 46 — мобильный Insights, закрытие блокера (раунд 2 доведён вручную)

Дата 2026-07-25. Раунд 2 workflow применил рефактор, но упал на сетевой ошибке до финального отчёта и до прогона loops. Довёл вручную.

**Блокер дуального ревью (закрыт)**: run-логика разбора (period-state, state-машина, `generate`) была инлайн в `app/m/insights/page.tsx` и дублировала `useDashboard`. Вынесена в общий примитив `hooks/useInsightRun.ts` (idle/loading/error/ready, выбор периода, `insightsAPI.create`); и `useInsights`, и `useDashboard` теперь висят на нём. Страница `/m/insights` — markup-only.

**Файлы (new)**: `hooks/useInsightRun.ts`, `hooks/useInsightRun.test.ts`, `hooks/useInsights.ts`, `hooks/useInsights.test.ts`, `app/m/insights/page.tsx`.
**Файлы (mod)**: `hooks/useDashboard.ts` (переезд на примитив), `app/insights/page.tsx` (markup-only на `useInsights`), `lib/routes.ts` (`hasMobile:true` для insights — реестр теперь полностью покрыт мобильными близнецами), `lib/view-mode.test.ts`, плюс 10 тест-файлов с `mock.module('@/lib/api')`.

**Довод вручную после падения раунда 2**:
- Тесты падали с `Export named 'insightsAPI' not found`: bun делит реестр `mock.module('@/lib/api')` на весь прогон, и 10 фабрик не объявляли `insightsAPI` — при первой линковке имя выпадало. Добавил no-op заглушку `insightsAPI` в каждую из 10 фабрик.
- eslint error `Cannot access refs during render` в `useInsightRun.ts:57`: запись `onReadyRef.current` перенесена из тела рендера в `useEffect`.
- Почищены две unused-var warning в новом `useInsightRun.test.ts`.

Feedback loops: `bun test` 345/345 green, `bunx tsc --noEmit` clean, `bunx eslint .` 0 problems, `bun run build` green.

### Тикет 56 — календарная дата по локальной зоне вместо UTC

Дата 2026-07-25. `toISODate` в `lib/date.ts` строила `YYYY-MM-DD` через `d.toISOString()`, то есть отдавала календарную дату в UTC. На UTC+3 запись, сделанная в 00:30, уходила вчерашним днём. Переведена на локальный календарь (`getFullYear`/`getMonth`/`getDate` с zero-padding через `padStart`); `todayISO` наследует поведение без изменений. Докстринг про UTC-эффект снят. Downstream-экраны (`app/today`, `app/m/today`, `app/journal`, `app/table`, `lib/chart-data.ts`) не менялись — они висят на едином `toISODate` и наследуют исправление.

**Файлы (mod)**: `lib/date.ts` (локальный календарь), `lib/date.test.ts` (кейсы под явной `TZ=Europe/Moscow`: полночь → сегодня, 23:59, високосное 29 февраля, zero-pad).

Feedback loops: `bun test` (весь фронт) 348/348 green, `bunx tsc --noEmit` clean, `eslint` exit 0. Коммиты не делались, issue не двигался.

### Тикет 60 — плюс в Today: тап без ввода добавляет 1

Дата 2026-07-25. Кнопка «+» в `QuickNumberRow` перестала быть disabled и теперь при пустом поле пишет запись со значением `1` — стакан воды отмечается одним тапом, без клавиатуры. Логика «что записать по тапу» вынесена в чистую функцию `quickAddAmount`: пусто → `1`, число → это число (отрицательные разрешены как способ исправить опечатку), ноль и нечисловой ввод → ничего не делать молча. Шаг не запоминается: после успеха поле очищается, следующий тап снова даёт `1`. In-flight лока и `Idempotency-Key` нет — пять быстрых тапов это пять намеренных инкрементов. Итог за день по-прежнему считает сам компонент, владение итогом уходит в тикет 61.

**Файлы (new)**: `lib/quick-add.ts`, `lib/quick-add.test.ts`, `components/QuickNumberRow.test.tsx`.
**Файлы (mod)**: `components/QuickNumberRow.tsx` (снят `saving`-флаг и `disabled`, разбор ввода делегирован `quickAddAmount`, добавлен `ref` на инпут).

**Закрыто по дуальному ревью**:
- Acceptance «мусорный ввод не создаёт запись» в реальном UI работал наоборот: `input type="number"` отдаёт `value === ''` для любого нечислового ввода, поэтому «abc» + тап писал `1`, а ветка `Number.isFinite` через UI была недостижима. `quickAddAmount` получила второй аргумент `{ hasBadInput }`, компонент читает `inputRef.current.validity.badInput` в момент сабмита — это вердикт самого DOM о тексте, который он отказался разобрать, и контрол в этом состоянии больше не шлёт change-событий, из которых можно было бы синхронизировать state.
- Компонентный тест на этот кейс подменяет `validity` через `Object.defineProperty`: happy-dom всегда рапортует `badInput: false`, поэтому вердикт браузера приходится подставлять. Тест проверен на невакуумность — без проводки в компоненте падает.
- Review-маркер в `QuickNumberRow.tsx` приведён к формату §9 (один ticket-id вместо списка через запятую).

Feedback loops: `bun test` (весь фронт) 364/364 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems, `bun run build` green.

### Тикет 49 — плюс в шапке и клавиатура в полноэкранном листе

Дата 2026-07-26. Два дефекта, найденных на реальном iPhone.

Плавающий FAB (`fixed bottom-20 right-5`) на всех четырёх мобильных экранах садился ровно на кнопки редактирования и удаления последней карточки. Плюс переехал в шапку `/m`: экран по-прежнему владеет действием, но рисует его через портал в слот `#mobile-header-action`, который выдаёт layout. Слот читается через `useSyncExternalStore` (сервер и гидрация — `null`, клиент — узел или `false`), а не копированием DOM в state из эффекта: так нет ни рассинхрона гидрации, ни кадра, в котором кнопка мигает посреди страницы. Без слота (страница отрендерена вне мобильной оболочки — как в тестах) кнопка остаётся на месте, а не исчезает.

`FullScreenSheet` под открытой клавиатурой уводил бар с «Отмена»/«Готово» за верхний край: iOS не сжимает layout viewport под клавиатуру, он сжимает visual viewport и скроллит страницу внутри него, поэтому `100dvh` держал лист выше видимой области. Лист теперь следит за `window.visualViewport` (`height` + `offsetTop` → инлайновые `height`/`top`/`bottom:auto`), `100dvh` остаётся стартовым размером до первого скрипта. Второй симптом — «первый тап по Готово ничего не делает»: нажатие на бар уводило фокус из поля, клавиатура закрывалась, layout перекладывался под пальцем и click не долетал. Обе кнопки бара гасят `mousedown` (`preventDefault`), фокус остаётся в поле, клавиатура не закрывается, click приходит с первого раза.

**Файлы (new)**: `components/mobile/HeaderAction.tsx`, `components/mobile/HeaderAction.test.tsx`.
**Файлы (mod)**: `components/mobile/FullScreenSheet.tsx` (слежение за visual viewport, `mousedown`-гашение), `components/mobile/FullScreenSheet.test.tsx` (фейковый `visualViewport`, снятие подписки, гашение `mousedown`), `app/m/layout.tsx` (слот в шапке), `app/m/entries/page.tsx`, `app/m/categories/page.tsx`, `app/m/categories/[id]/page.tsx`, `app/m/journal/page.tsx` (FAB → `MobileHeaderAction`, текст пустых состояний про плюс в шапке).

Feedback loops: `bun test` 372/372 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems, `bun run build` green. Проверка на устройстве — за пользователем.

### Тикет 61 — итог за день владеет useToday

Дата 2026-07-28. Итог квик-инпута перестал быть локальной выдумкой компонента. `QuickNumberRow` стал полностью контролируемым: `total` приходит пропом, тап только сообщает наверх сумму (`onAdd`), а `entriesAPI.create` и текст ошибки ушли в хук — рефетч по возврату на вкладку теперь сразу даёт верное число, в том числе после записи с другого устройства.

Оптимистичный инкремент живёт в `useToday.addNumber`: запись рисуется в `entries` до ответа сервера, при падении вычитается ровно её вклад (остальные тапы остаются), сообщение уходит в общий `error`-баннер страницы. Гонка «рефетч во время полёта POST» решена вторым списком `optimisticEntries`, который мержится поверх снапшота с дедупом по `id`: локальная запись получает отрицательный `id` (сервер такие не выдаёт), после успеха перенимает серверный, а первый снапшот, который её вернул, вытесняет копию — поэтому инкремент не теряется и не считается дважды.

Анимация итога — `key={total}` на узле с `.animate-total-bump`: узел перемонтируется на каждое изменение и проигрывает анимацию заново, при быстрых тапах видно каждый засчитанный.

**Файлы (mod)**: `hooks/useToday.ts` (+`addNumber`, слияние оптимистичных записей, прунинг в `loadData`), `hooks/useToday.test.ts` (оптимистичный показ, откат одного тапа из трёх, рефетч в полёте, однократный учёт после рефетча, чужая запись), `lib/today-entries.ts` (+`optimisticNumberEntry`, `mergeOptimisticEntries`), `components/QuickNumberRow.tsx` (контролируемый `total`, `onAdd`, анимация), `components/QuickNumberRow.test.tsx` (проверяется проводка, а не запись в API), `app/today/page.tsx`, `app/m/today/page.tsx` (проброс `total`/`onAdd`), `app/globals.css` (`@keyframes total-bump`).

Feedback loops: `bun test` 378/378 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems, `bun run build` green.

### Тикет 73 — экран разбора дня на обоих шеллах

Дата 2026-07-30. Текст дня и дата уходят в LLM, возвращается план числовых записей, пользователь снимает лишние галки и пишет всё одной транзакцией.

Логика целиком в `useDailySummary` — обе страницы отличаются только разметкой и тем, куда уходят после успеха (`/entries` против `/m/entries`). Дефолт галки: уверенно размещённая метрика включена, помеченная моделью как неуверенная или неправдоподобная — выключена. Асимметрия намеренная: метрика, уехавшая не в ту категорию, разгребается по одной записи через Entries, поэтому сомнительное должно стоить осознанного клика.

Не размещённое моделью показывается отдельной секцией без чекбоксов и не создаёт ничего: смешивать «записать день» и «поменять схему» под одной кнопкой — две очень разные цены ошибки. Схема категорий меняется конструктором на `/onboarding`.

Ошибка применения оставляет и план, и текст на экране: применение на сервере всё-или-ничего, поэтому тот же экран отправляется повторно как есть. Ошибка генерации тоже не трогает текст — пересказывать день заново из-за недоступного бэкенда экран не просит никогда.

**Файлы (new)**: `hooks/useDailySummary.ts` (+ тест), `app/daily-summary/page.tsx` (+ тест), `app/m/daily-summary/page.tsx` (+ тест).
**Файлы (mod)**: `lib/api.ts` (`dailySummaryAPI` + типы плана), `lib/routes.ts` и `lib/routes.test.ts` (экран в реестре, первым в списке «More»), `components/route-icons.ts` (иконка `NotebookPen`).
**Файлы (mod, механически)**: 15 существующих тест-файлов — в их `mock.module('@/lib/api', …)` добавлена заглушка `dailySummaryAPI`. Bun фиксирует набор экспортов модуля при первой линковке и делит его на весь прогон, поэтому мок без нового экспорта удаляет его у той сьюты, которая загрузилась позже.

Feedback loops: `bun test` 452/452 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems, `bun run build` green (обе новые страницы статические).

### Тикет 73, раунд 2 — предпросмотр называет категорию и поле

Дата 2026-07-30. По ревью: строка метрики показывала `категория #1 · поле #2` — предпросмотр просил подтвердить запись, которую нечем проверить. `useDailySummary` тянет каталог (`categoriesAPI.getAll()`) при монтировании и отдаёт наружу `resolveLabel(metric) -> { categoryName, fieldName }`; обе страницы рендерят имена.

Разрешение — по паре (категория, поле), той же, что валидирует бэкенд: `field_id` из чужой категории именем той категории не объясняется и остаётся id. Каталог грузится только ради подписей, поэтому его падение проглатывается — строки читаются как id, а день всё равно записывается; блокирующий баннер из-за проблемы с именами остановил бы запись дня.

**Файлы (mod)**: `hooks/useDailySummary.ts` (+`resolveLabel`, загрузка каталога), `hooks/useDailySummary.test.ts` (известный id → имя, неизвестный → id, недоступный каталог не ломает поток), `app/daily-summary/page.tsx`, `app/m/daily-summary/page.tsx` (рендер имён), их тесты (ассерты на имена и на fallback к id).

Принятый риск (бэкенд, зафиксирован в #74): `POST /daily-summary/apply` не принимает `Idempotency-Key`, поэтому повторное **успешное** применение того же плана создаёт вторые записи за дату, а таблица их складывает. Повтор после ошибки безопасен — транзакция всё-или-ничего. Цена — ручное удаление лишних записей через Entries.

### Тикет 74 — текст дня в предпросмотре и один ключ на один план

Дата 2026-07-30. В плане появилась журнальная операция, и предпросмотр честно называет, что с ней произойдёт: чекбокс подписан «Дополнить запись дня» или «Создать запись дня» — это разные обещания, и одна подпись на оба случая означала бы согласие вслепую. Операция приходит включённой: дописывание ничего не теряет.

Рядом — «Заменить текст», выключенный и названный заменой, а не «обновить»: это единственный контрол на экране, который стирает написанное. Показывается он только когда есть что терять (`existing_entry_id !== null`). Режим не хранится в состоянии операции, а выводится из тумблера при отправке, поэтому `replace` не может уехать на сервер при снятой галке.

Ключ идемпотентности выпускается на план, а не на клик: ретрай после сетевого таймаута (когда запись, возможно, уже прошла) несёт тот же ключ — ровно это и позволяет серверу узнать повтор. Новый драфт — новое намерение, новый ключ, и замена сбрасывается вместе с ним.

Кнопка записи больше не завязана на число метрик: день, где все числа сняты, а текст оставлен, записывается.

**Файлы (mod)**: `hooks/useDailySummary.ts` (журнальная операция, `journalEnabled`/`journalReplace`/`canReplaceJournal`/`canApply`, ключ на план) и его тест; `lib/api.ts` (типы `JournalMode`/`JournalOp`, `apply` шлёт журнал и заголовок `Idempotency-Key`); `app/daily-summary/page.tsx` и `app/m/daily-summary/page.tsx` (секция/карточка текста дня) и их тесты.

Feedback loops: `bun test` 474/474 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems.

## PHASE-01/75 — отметки чек-листа в предпросмотре дня

Дата 2026-07-30. В плане появились отметки чек-листов, и на обоих экранах они живут своей секцией — не среди метрик. Обещание разное: метрика пишет новое число, галка ложится на ту же карту дня, которую руками правит Today. Поэтому на каждой строке стоит название категории: «B12» само по себе не говорит, какой чек-лист сейчас изменится.

Снять галку из предпросмотра нельзя, и это не запрет в UI, а форма данных: у `CheckOp` нет поля значения, отправляется только список того, что ставим. Пустой список — «не упомянуто», единственное прочтение, которое ничего не снимает. Слияние с текущим состоянием дня делает бэкенд внутри транзакции: клиент состояние не знает и знать не должен, иначе гонка между открытым предпросмотром и щелчком на Today стирала бы отметку.

Уверенная отметка приходит включённой, помеченная моделью как сомнительная — выключенной, как и у метрик. `enabledCount` считает метрики и галки одним числом: пользователь читает «Записать выбранное (2)» и не различает, что из этого число, а что галка.

**Файлы (mod)**: `lib/api.ts` (тип `CheckOp`, необязательный `checklist` в плане, `checklist` третьим аргументом `apply`); `hooks/useDailySummary.ts` (`checklist`/`checkStates`/`toggleCheck`, `checkCheckboxLabel`, `CHECKLIST_TITLE`, `resolveLabel` по паре id) и его тест; `app/daily-summary/page.tsx`, `app/m/daily-summary/page.tsx` и их тесты.

Feedback loops: `bun test` 494/494 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems.

### Раунд 3 (правки по ревью)

- `lib/api.ts` — **mod**: комментарий про необязательные `checklist?`/`journal?` в `DailySummaryPlan` теперь ссылается на заведённый тикет — `issues/PHASE-01/backlog/83-daily-summary-plan-fields-required.md` (#83). TODO без issue reference нарушал CLAUDE.md §3; сам `?` снимается после выкатки, в которой бэкенд и фронтенд уходят вместе.

Feedback loops раунда 3: `bun test` 494/494 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems.

## 2026-08-02 — PHASE-01/84 голосовой ввод дня с /m/today

Дата 2026-08-02. Разбор дня из текста работал целиком, но добраться до него можно было только с отдельной страницы и только напечатав пересказ руками. Тикет закрывает оба входных барьера.

**Распознавание речи — `hooks/useSpeechRecognition.ts`.** Обёртка над Web Speech API: непрерывная `ru-RU`-сессия, отдающая наружу только законченные фразы. Хук не накапливает текст сам — накопитель был бы вторым источником правды, который молча перезапишет то, что пользователь исправил руками. Формирующаяся фраза (`interim`) живёт отдельно и только показывается: движок переписывает её пословно, и пустить её в textarea значит увести каретку из-под редактирующего. `onResult` читается через ref, потому что вызывающий передаёт замыкание над редактируемым текстом — новая функция на каждое нажатие клавиши, — а пересоздание сессии из-за этого обрывало бы человека на полуслове. `supported` читается через `useSyncExternalStore`: сервер должен отрисовать экран без микрофона, и это тот API, который позволяет двум рендерам разойтись намеренно. Размонтирование делает `abort` — открытый микрофон за закрытой шторкой пользователь увидит в статус-баре и никогда не свяжет с этим приложением.

**Шторка — `components/mobile/VoiceDaySheet.tsx`.** Оба шага под одной кнопкой бара, которая меняет имя вместе с шагом: сначала «Разобрать день», потом «Записать (N)». Вторая кнопка для второго шага увела бы самое ответственное действие дня туда, где палец его ищет. Распознанное дописывается в обычную textarea: распознавание ошибается предсказуемо и именно на тех словах, из которых состоит пищевой дневник, а неисправимый транскрипт — это день, который бросают, а не чинят.

**Общий предпросмотр — `components/mobile/DayPlanPreview.tsx`.** Карточки плана переехали из `app/m/daily-summary/page.tsx` без изменения поведения (16/16 тестов страницы зелёные до и после), потому что у них появился второй читатель. Кнопку подтверждения компонент не содержит: страница держит её в колонке контента, шторка — в баре, и это единственное, чем два экрана различаются.

**Оценочные метрики.** Строка с `estimated` подписана на обоих экранах разбора — и на мобильном, и на десктопном. Подпись нейтральная, не красная: оценка — нормальный исход описания еды, а красный сказал бы, что что-то пошло не так. Формулировка живёт в `useDailySummary` рядом с остальными общими подписями именно потому, что угаданное число, прочитанное как названное, — та самая ошибка, ради предотвращения которой флаг и заведён.

**Точка входа.** Кнопка над секциями Today, а не рядом с карточкой: продиктованный день заполняет сразу несколько категорий, чек-лист и текст дня, поэтому принадлежит экрану, а не какой-то одной карточке. После записи шторка закрывается и Today перезагружается — оставить старые суммы значит получить дважды записанный обед.

Тронутые файлы:

- `hooks/useSpeechRecognition.ts` + `hooks/useSpeechRecognition.test.ts` — **new** (10 тестов).
- `components/mobile/VoiceDaySheet.tsx` + `components/mobile/VoiceDaySheet.test.tsx` — **new** (13 тестов).
- `components/mobile/DayPlanPreview.tsx` — **new**: карточки метрики/галок/журнала/нераспознанного + `planIsEmpty`/`planHasWrites`/`EMPTY_PLAN_MESSAGE`.
- `app/m/today/page.tsx` — **mod**: кнопка «Рассказать день», состояние шторки, перезагрузка после записи. `app/m/today/page.test.tsx` — **new** (3 теста).
- `app/m/daily-summary/page.tsx` — **mod**: свои копии карточек заменены общим компонентом.
- `app/daily-summary/page.tsx` — **mod**: подпись оценочной метрики.
- `hooks/useDailySummary.ts` — **mod**: `ESTIMATED_NOTE`.
- `lib/api.ts` — **mod**: `estimated?: boolean` на `LogMetricOp`.
- `components/mobile/FullScreenSheet.tsx` — **mod**: опциональные `doneLabel` и `doneDisabled` (у существующих вызовов поведение прежнее).

Feedback loops: `bun test` 520/520 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems.

## 2026-08-10 — PHASE-01/73 перестановка полей в редакторе категории

Дата 2026-08-10. Порядок полей внутри категории задавался ровно один раз — тем, в каком порядке их создали. Чтобы поднять нужное поле наверх, категорию приходилось пересобирать, а поле, пересозданное без `id`, уводило свои `entry_values` каскадом. Бэкенд менять не пришлось: `Field.order` сквозной, а `save` и так выводит `order` из позиции в списке.

**`moveField(index, direction)` в `useCategoryDraft`.** Свап соседей целыми объектами, вместе с `id`: перестановка, которая двигала бы только имя и тип, для бэкенда выглядела бы как переименование двух полей, и вся история значений уехала бы не в ту колонку. Выход за границы списка — no-op, поэтому экраны вешают обработчики безусловно, а `disabled` у крайних кнопок остаётся чисто визуальным сигналом.

**Стабильные ключи строк — `DraftField.key`.** Оба редактора рендерили поля с `key={index}` и обосновывали это тем, что список только дополняется и фильтруется. После перестановки обоснование неверно: React переиспользовал бы DOM той строки, что раньше стояла на этой позиции, и фокус с кареткой уехали бы на соседнее поле. Ключ выдаётся один раз на строку (`mintFieldKey`) и едет вместе с ней. В пейлоад он не попадает — `toFieldPayload` снимает его и заодно проставляет `order` по позиции.

**Кнопки.** ↑/↓ в правом углу карточки поля, рядом с Remove, на обоих шеллах; на мобиле подчиняются `TAP_TARGET_PX`. Стиль общий (`reorderButtonClass` в `lib/ui-constants`): тихий, вторичный рядом с деструктивным Remove, с отчётливо инертным disabled — на концах списка это единственный сигнал, что нажатие ничего не сделало. У десктопного `FieldRow` появились `aria-label` на имени поля и на кнопках — раньше строка была безымянной для тестов и для скринридера.

Тронутые файлы:

- `hooks/useCategories.ts` — **mod**: `DraftField`, `FieldMoveDirection`, `moveField`, `toFieldPayload`. `hooks/useCategories.test.ts` — **mod** (4 новых теста).
- `app/categories/page.tsx` — **mod**: `FieldRow` с позицией, кнопками и ключом по строке. `app/categories/page.test.tsx` — **mod** (3 новых теста, во фикстуру добавлено второе поле).
- `app/m/categories/page.tsx` — **mod**: то же для `FieldCard`. `app/m/categories/page.test.tsx` — **mod** (4 новых теста).
- `lib/ui-constants.ts` — **mod**: `reorderButtonClass`.

Feedback loops: `bun test` 531/531 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems, `next build` ok.

### Раунд 2 (правки по ревью, PHASE-01/73)

Дата 2026-08-10. Раунд 1 сделал перестановку в редакторе, но нигде не закрепил, что «порядок полей» — это `order`. Раунд 2 закрывает именно это: один источник порядка на всём пути от БД до формы записи, плюс доступность самой перестановки.

**Порядок как контракт, а не как совпадение.**

- `backend/app/models/category.py` — **mod**: `Category.fields` получил `order_by="(Field.order, Field.id)"`. Перестановка меняет только `order` (id сохраняются, строки в таблице не двигаются), поэтому без сортировки в relationship ответ выглядел ровно так же, как до перестановки. Тай-брейк по `id` нужен полям одного батча — у них `order` совпадает.
- `backend/tests/test_categories.py` — **mod**: тест `test_reordered_fields_come_back_in_the_new_order` (красный до правки: `[1, 2] == [2, 1]`) — PATCH меняет `order`, и порядок держится и в ответе PATCH, и в отдельном GET категории, и в списке категорий, которым питается Today.
- `lib/today-categories.ts` — **mod**: `orderedFields(category | fields)` — единственное определение порядка полей во фронтенде. Четыре копии `.sort((a, b) => a.order - b.order)` (`today-categories` ×2, `hooks/useTable`, `lib/chart-data`, `lib/chart-utils`) заменены на него; вход не мутируется, тай-брейк по `id`.
- `hooks/useCategories.ts` — **mod**: черновик сеется из `orderedFields(editing)`, а не из массива как он приехал. `save` выводит `order` из позиции, поэтому черновик в порядке доставки показывал бы одно, а сохранял другое — то есть отменял бы только что сделанную перестановку самим фактом открытия редактора.
- Потребители порядка переведены на хелпер: `components/EntryForm.tsx`, `components/EntryCard.tsx`, `components/mobile/EntryEditorSheet.tsx`, `lib/entry-values.ts` (`toEntryValues`), список полей в карточке категории `app/categories/page.tsx`.

**Дедупликация и типы.**

- `components/FieldReorderButtons.tsx` — **new**: общая пара ↑/↓ вместе с `moveFieldLabel` — единственный источник aria-имён, на которые опираются тесты обоих шеллов. Обе страницы её импортируют; десктоп рендерит `p-2`, мобила — 44px-таргеты через проп `touch`.
- `app/categories/page.tsx`, `app/m/categories/page.tsx` — **mod**: `FieldRowProps.field` и `FieldCardProps.field` типизированы как `DraftField`, а не `FieldCreate` — keyed-row контракт (родитель ключует строку по `field.key`) теперь выражен в типе, а не только в комментарии.
- `hooks/useCategories.ts` — **mod**: no-op `void key;` в `toFieldPayload` убран. Без него линт даёт warning (`ignoreRestSiblings` в конфиге не выставлен), поэтому вместо no-op стоит `eslint-disable-next-line` с однострочным обоснованием — CLAUDE.md §3.

**Доступность перестановки.**

- `hooks/useCategories.ts` — **mod**: `moveAnnouncement` + `fieldMovedMessage(position)`. Проверка границ переехала из апдейтера наружу: апдейтер снова чистый, а объявление звучит только для состоявшегося перемещения.
- Оба шелла — **mod**: `role="status" aria-live="polite"` рядом со списком полей.
- `components/FieldReorderButtons.tsx` — фокус едет за строкой: нажатая кнопка приезжает на новую позицию, на краю списка — задизейбленной, и фокус проваливался в документ. Теперь фокус уходит на кнопку, которая ещё что-то делает (обратное направление).

**Мобильный шелл на 320px.**

- `app/m/categories/page.tsx` — **mod**: строка действий карточки поля стала `flex-wrap`. В ней теперь соседствуют чекбокс Required и три 44px-таргета (вверх, вниз, Remove); на 320px после отступов шторки и карточки запас — единицы пикселей, и без переноса браузер разрешает переполнение сжатием тап-таргетов.

**Тесты (мод/new).**

- `hooks/useCategories.test.ts` — **mod**: черновик из фикстуры вне порядка (ids [8, 7], order [1, 0]) рендерит 7 затем 8; объявление после перемещения; молчание при no-op на краю.
- `app/categories/page.test.tsx`, `app/m/categories/page.test.tsx` — **mod**: live-регион с обновлённым текстом; фокус после перемещения; карточка категории перечисляет поля по `order`; узкий экран 320px — три 44px-таргета плюс перенос строки.
- `components/entry-field-order.test.tsx` — **new**: оба шелла формы записи перечисляют поля в сохранённом порядке, и пейлоад значений уходит в том же порядке.
- `lib/today-categories.test.ts` — **mod**: `orderedFields` — категория и голый список, тай-брейк по id, отсутствие мутации входа.

Feedback loops раунда 2: `bun test` 546/546 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems, `bun run build` green (21 роут); backend — `pytest` 311/311 green, `ruff check` clean, `ruff format --check` clean, `mypy app` clean.

## 2026-08-10 — PHASE-01/73 hero-карточка дня (фронтенд)

Дата 2026-08-10, тикет `73-dashboard-hero-today-ring`. Кольцо показывало «всего записей / 10» и после сотни записей было залито навсегда. Теперь hero-карточка отвечает на три вопроса про сегодня: сколько записано за день, что записано последним и что стоит сделать дальше.

**Честное кольцо.** Заполнение считается покрытием дня — сколько отслеживаемых категорий уже имеют запись, — а не счётчиком против фиксированной цели. Счётчик по определению не умеет опустеть в полночь, и именно это делало старое кольцо бессмысленным. Если на сегодня не отслеживается ничего, кольцо падает к бинарному вопросу, на который ещё может ответить честно: записано ли за день хоть что-нибудь.

**Время записи, не время события.** Строка последней активности говорит `Logged 14 minutes ago`. `created_at` — момент сохранения, и если день заносят вечером, «09:15» было бы враньём про тренировку. Таймстемп без обозначения зоны читается как UTC: браузер иначе сдвинул бы его на офсет пользователя и превратил запись минутной давности в трёхчасовую (а восточнее Гринвича — в будущую).

**Совет дня — правила, не модель.** Строка на экране при каждой загрузке, поэтому она обязана быть бесплатной, мгновенной и одинаковой для одного и того же дня. Приоритет — по тому, сколько дню ещё нужно от пользователя: нетронутый день важнее всего (но поздним вечером тот же смысл резче звучит как «серия под угрозой»), названная незакрытая привычка важнее дневника, потому что это меньшая просьба.

**Меньше данных, а не больше.** Hero задаёт два узких вопроса вместо чтения истории: окно «вчера-сегодня» (из него же берётся, было ли что-то вчера — иначе про серию говорить нельзя) и одна последняя сохранённая запись через новый `sort=created_at_desc&limit=1`. Общий список записей остаётся только под KPI «Entries» и ленту активности, которую заменяет #76.

Тронутые файлы: 11 (3 new, 8 mod).

- `lib/daily-tip.ts` — **new**: `pickDailyTip` — чистая функция правил, без часов и сети: и момент, и данные приходят снаружи.
- `lib/relative-time.ts` — **new**: `formatRelativeTime` / `formatLoggedAgo`; будущий таймстемп (клиентские часы отстают) читается как `just now`, нераспознанный — как `recently`.
- `hooks/useDashboard.test.ts` — **new**: hero считается из дневного окна при заведомо «богатой» истории, последняя запись спрашивается у API, а не ищется в списке.
- `lib/dashboard-stats.ts` — **mod**: `computeDashboardHero` — кольцо, последняя запись и совет; повторная запись в ту же категорию не переполняет кольцо, запись исчезнувшей категории всё равно называется.
- `lib/api.ts` — **mod**: `EntrySort` и параметр `sort` у `entriesAPI.getAll`.
- `lib/ui-constants.ts` — **mod**: `ENTRIES_TODAY_LABEL`, `NO_ENTRIES_YET`, `heroLastEntryLine` — единицы измерения появятся в #75, поэтому значение дописывается голым и может отсутствовать.
- `hooks/useDashboard.ts` — **mod**: один `new Date()` на всю загрузку (граница суток, час для совета и «N ago» обязаны совпадать), дневное окно, последняя запись, дата свежайшей заметки дневника.
- `app/page.tsx`, `app/m/page.tsx` — **mod**: hero в обоих шеллах одной формулировкой.
- `lib/dashboard-stats.test.ts`, `lib/daily-tip.test.ts` — **mod/new**: матрица случаев совета и поведение кольца.
- `hooks/useToday.test.ts`, `hooks/useEntries.test.ts`, `hooks/useCategories.test.ts`, `hooks/useCategoryDetail.test.ts`, `hooks/useEntryDraft.test.ts` — **mod**: в моки `@/lib/api` добавлен `journalAPI`. Мок заменяет модуль на весь процесс, поэтому неполный мок в одном файле удаляет экспорт для того, кто загрузится позже — та же причина, по которой в них уже жил `tableAPI`.

Feedback loops: `bun test` 580/580 green, `bunx tsc --noEmit` clean, `bun run lint` 0 problems.

## 2026-08-30 — PHASE-03/86, 87, 88 экран дня (фронтенд, волна A)

Дата 2026-08-30, тикеты `86-day-exists-rule-set-and-day-page`, `87-plan-sections-items-and-canon-validation`, `88-plan-marks-three-states-and-notebook`, ветка `phase-03-a`. Одна запись на три тикета: во фронтенде это один экран, который трижды дорос — сначала до дня и его правила, потом до плана и расписания, потом до отметок и блокнота. `#107` (граница суток) UI-слоя не имеет и здесь не отражён; бэкендовая половина всех четырёх — в `backend/SESSION_REVIEW.md`.

Записывается сюда, а не туда: `.claude/CLAUDE.md` §9 требует per-session summary в `SESSION_REVIEW.md` **сервиса**, а фронтенд — отдельный сервис со своим файлом. На приёмке волны обнаружилось, что вся волна ушла в бэкендовый файл, и вход для ревьюера фронтенда отсутствовал.

**Какой сегодня день, решает сервер.** `/day` не подставляет дату из браузерного календаря: `useDay(null)` зовёт `dayAPI.getToday()`, и день называет сервер по своей границе (04:00). Между полуночью и четырьмя календарь браузера и граница суток расходятся, и экран открыл бы день, в который больше никто ничего не пишет. Дата в `/day/[date]` наоборот передаётся в API как есть — кривая дата обязана вернуться 422 сервера, а не молча исправленной датой.

**Два шелла, одно состояние.** `useDay` и `useDayMarks` держат всё; `DayScreen` и `MobileDayScreen` отличаются только разметкой. Дублирование в шапке мобильного шелла (loading, error, разбор `detail`) на сегодня скопировано дословно — около сорока строк, названо на приёмке, не вычищено.

**Клик применяется сразу и шлёт состояние, а не шаг.** `useDayMarks` ставит отметку локально и отправляет явное целевое состояние; отказ сервера откатывает клик. «Следующее по кольцу» заставило бы две вкладки понимать один клик по-разному, а явное состояние делает повтор того же запроса пустой операцией и оставляет победителем последнюю запись — ровно то, что делает `ON CONFLICT` на сервере.

**Счётчик задач считается на клиенте.** Шапка обязана двигаться вместе с кликом, а не через круг до сервера и обратно; серверный счёт приезжает со следующим чтением дня и разногласие снимает. `skipped` в строке счётчика называется отдельно и никогда не сворачивается ни в «закрыто», ни в «не сделано»: снятая задача не была ни закрытой, ни проваленной, и складывание её с любой из двух врёт ровно в ту сторону, которую читатель и пришёл проверить.

**Кольцо клика — данные по обе стороны.** `MARK_CYCLE` в `lib/marks.ts` — зеркало `app/day/marks.py`, списком, а не цепочкой `if`, чтобы две стороны сверялись глазами. `skipped` на кольце нет: «стало неактуально» — суждение о плане, и попадать в него четвёртым щелчком человек не должен, поэтому у него отдельная кнопка.

**Наложения окон приезжают с сервера.** `overlappingItemIds` раскладывает ответ самосоединения в множество; экран стал потребителем факта, а не его вторым вычислителем. Длительность окна тоже считает сервер — поэтому окно через полночь читается как час, а фронтенд про границу суток ничего не знает. Браузерный пояс используется ровно в одном месте, `formatMoment`: какой день — решил сервер, какие часы на стене — решает браузер.

**Правило дня показывается словами.** `ruleLines`/`ruleValidity` разворачивают строку `day_rule_set` в «Работа — 8 ч в день», «Стоп — 16:00», «действовало с … по …». Смысл версионированного канона в том, что читатель видит, **какими** числами судится именно этот день: 14 и 30 августа судятся разными.

**«Плана нет» — ответ, а не ошибка.** День без плана показывает дату, вид дня и правило плюс явную строку `NO_PLAN_TEXT`; пустой экран и 404 не дали бы отличить пустой день от неверного адреса.

Тронуто 51 файл (25 new, 26 mod), из них 22 mod — однострочная добавка `dayAPI` в мок `@/lib/api` уже существующих сьютов.

- `lib/day-format.ts` — **new** (+тест): `dayKindLabel`, `weekdayNames`, `formatMinutes`, `formatClock`, `formatRatio`, `ruleLines`, `ruleValidity` и строки `NO_PLAN_TEXT`/`NO_PLAN_HINT`/`LOAD_DAY_ERROR`. Чистые функции, обе шкуры рисуют одни и те же строки.
- `lib/plan.ts` — **new** (+тест): `formatMoment`, `formatWindow`, `formatDuration`, `overlappingItemIds`, `totalOverlapMinutes`, `itemKindsById`, названия видов секций и жёсткости по-русски.
- `lib/marks.ts` — **new** (+тест): `MARK_CYCLE`, `MARK_GLYPH`, `MARK_LABEL`, `nextMarkState`, `marksByItem`, `stateOf`, `noteOf`, `markStateLabel`, `taskCountsLine`, `DAY_NEVER_OPENED`.
- `hooks/useDay.ts` — **new** (+тест): день по дате или «сегодня по серверу»; отмена устаревшего запроса при смене даты и на unmount; баннер ошибки сбрасывается на входе, а не на успехе, чтобы не переезжать с провалившейся даты на загрузившуюся. Флаг `opened` выключен по умолчанию: агент, импорт и cron тоже читают дни, и если чтение считать открытием, «не открывал» перестанет быть устанавливаемым фактом.
- `hooks/useDayMarks.ts` — **new** (+тест): `cycle`, `setState`, `setNote`, локальный счётчик, множество `saving`, откат при отказе. Эффект синхронизации ключуется по строке-сигнатуре содержимого, а не по ссылке на массив: вызывающий обычно пишет `detail?.marks ?? []` — новый массив на каждый рендер, — и хук, который работает только когда о нём помнят `useMemo`, был бы ловушкой, а не хуком.
- `components/DayScreen.tsx` — **new** (+тест): десктопный экран — дата, вид дня, план секциями, расписание с наложениями, отметки, блокнот, правило дня, явное «плана нет». `NO_MARKS` — стабильная пустая ссылка: свежий `[]` на каждый рендер выглядел бы для `useDayMarks` новыми отметками и загонял экран в цикл.
- `components/mobile/MobileDayScreen.tsx` — **new**: та же информация в одну колонку, 44px-таргеты, ничего мельче `text-sm`. **Тестов нет**, шапка скопирована из `DayScreen.tsx` — долг назван на приёмке волны.
- `components/day/PlanSections.tsx` — **new** (+тест): секции по порядку, вложенные пункты, у задачи окно и критерий «сделано», подписи без своей колонки читаются обратно из `extra`; проп `marking` необязательный, поэтому план рисуется и без отметок.
- `components/day/DaySchedule.tsx` — **new** (+тест): часы дня — пункты, заявившие окно, с длительностью от сервера и подсветкой наложений из его же самосоединения.
- `components/day/PlanItemMark.tsx` — **new** (+тест): коробка, крутящая пусто → ✓ → ✕ → пусто по клику; `неактуально` отдельной кнопкой; поле «как прошло» появляется только у пункта с отметкой — полю без строки, куда сохраниться, некуда деть напечатанное. Черновик заметки коммитится на blur и заменяется, когда сохранённая заметка меняется извне.
- `components/day/DayNotebook.tsx` — **new** (+тест): одна textarea на день с явной кнопкой сохранения — недописанное предложение не должно становиться тем, что день запомнил.
- `app/day/page.tsx`, `app/day/[date]/page.tsx`, `app/m/day/page.tsx`, `app/m/day/[date]/page.tsx` — **new**: точки входа обоих шеллов.
- `lib/api.ts` — **mod**: `dayAPI` (`get`, `getToday`, `open`, `openToday`, `savePlan`, `setMark`, `saveNotebook`) и типы `Day`, `DayRuleSet`, `DayDetail`, `Plan`, `PlanSection`, `PlanItem`, `ScheduleEntry`, `ScheduleOverlap`, `PlanDocument`, `Mark`, `MarkState`, `TaskCounts`. `savePlan` ни одним компонентом не зовётся: он для `/day-open` ([#95]) и для тестов — редактирование плана в UI вне охвата волны.
- `lib/routes.ts` + `lib/routes.test.ts`, `components/route-icons.ts` — **mod**: экран Day в реестре, `hasMobileNested: true` (дата переезжает между шеллами), `inTabBar: null` — пять слотов таб-бара уже заняты, день открывают по ссылке с датой.
- 22 существующих тестовых сьюта — **mod**: `dayAPI` добавлен в мок `@/lib/api`. `bun` фиксирует имена экспортов модуля при первой линковке, поэтому частичный мок в одном файле удаляет член для того, кто загрузится следующим, — та же причина, по которой в них уже живут `tableAPI` и `journalAPI`.

Feedback loops: `bun test` 664/664 green (было 574 до волны), `bunx tsc --noEmit` clean, `bun run lint` 0 problems. `any`, `@ts-ignore` и `@ts-expect-error` в новом коде — ноль. Бэкенд той же волны: pytest 455/455, `ruff check`, `ruff format --check`, `mypy --strict app`, одна голова Alembic `e0b2d4f6a8c1`. `make check` целиком не прогонялся ни разу: его цель `test` поднимает постгрес в docker, а демон на машине не отвечает — тесты шли против локального постгреса на 5432, база `habit_tracker_test`.

Известные долги экрана, зафиксированные приёмкой волны: `DayScreen` и `MobileDayScreen` зовут `useDay(date, true)` без разбора даты, поэтому листание истории проставляет `opened_at` историческим дням и стирает разницу между непрожитым днём и прожитым пусто (чинится в [#90]); `MobileDayScreen` не покрыт тестами и дублирует шапку десктопного шелла.

## 2026-08-30 — PHASE-03/90 и PHASE-03/93: правки по ревью коммита ee5de9d

Волна закрыла два тикета одним коммитом и не оставила записи ни здесь, ни в бэкендовом файле.
Эта секция — за фронтенд; бэкендовая половина того же сеанса лежит в
`backend/SESSION_REVIEW.md`.

**Проза итога появилась на экране.** `summary.body_md` не рисовался нигде — grep по
`components/`, `hooks/`, `lib/`, `app/` находил его только в типе и в фикстурах, — хотя сам
тикет называет прозу половиной ценности записи. Закрытый день теперь показывает её через
существующий `components/Markdown.tsx`.

**Кнопка «Закрыть день» перестала слать пустой драфт.** Вместо `run({})` — поле прозы и поле
минут работы; уходит только то, что заполнено. Пустая коробка — это «не сказал», а не `null`:
сервер после правок этого же сеанса пишет присланные ключи и остальную строку не трогает, так
что нулём это различие стирать больше нечем.

**Переопределение больше не предлагается импортированному дню.** Строка с `source: 'import'`
приходит с `closed: true` и попадала ровно в ветку переопределения — а клик по ней стирал прозу
августа и переводил день под пересчёт по отметкам, которых у него нет. Сервер отвечает на это
409; экран называет причину вместо кнопки, которая не может сработать.

- `components/day/DayVerdict.tsx` — **mod**: рендер `body_md`, форма закрытия (проза +
  `work_minutes`), `closingDraft()` шлёт только заполненное, блок переопределения снят с
  импортированного дня и заменён строкой `IMPORTED_VERDICT`. В докстринге записано, что каждая
  кнопка шлёт только набранное здесь и почему.
- `components/day/DayVerdict.test.tsx` — **mod**: +4 теста — проза закрытого дня видна, драфт
  несёт только заполненные поля (отдельно проза, отдельно минуты), импортированному дню
  переопределение не предлагается.
- `components/goals/GoalsBoard.tsx` — **mod**: `nextStatus` → `toggleDone`, кнопка подписана
  действием («Закрыть»/«Открыть»), статус и дата закрытия стоят рядом отдельной строкой. В
  докстринге сказано, почему `in-progress` и `dropped` ставятся только через API.
- `hooks/useGoals.test.ts` — **new**: покрыт хук, у которого не было тестов рядом с `useDay` и
  `useDayMarks` — сброс `payload` в `null` при отказе, перечитывание доски после `markMilestone`,
  отказ `patchMilestone` в `error` со снятием кода из `saving`, и результат запроса, пришедший
  после размонтирования.
- `lib/api.ts` — **mod**: комментарий к `VerdictReason` объяснял порядок причин приоритетом
  `config.md`, хотя порядок ставит переработку выше якорей; настоящая причина — переработка
  вызывает пропущенные после неё якоря. `DayCloseDraft` документирован как «только заполненные
  поля».
- 24 существующих тестовых сьюта — **mod**: в mock `@/lib/api` добавлен `goalsAPI`. `useGoals.ts`
  до этого сеанса не загружался ни в одном прогоне (`GoalsBoard.test.tsx` мокает сам хук), и
  первый же его линк упал: bun фиксирует имена экспортов модуля при первом линке и делит реестр
  на весь прогон. Та же причина, по которой в этих файлах уже живут `dayAPI` и `onboardingAPI`.

Долг, не закрытый здесь: `MobileDayScreen` по-прежнему без тестов и с копией шапки десктопного
шелла; `savePlan` из `dayAPI` не зовётся ни одним компонентом.

Feedback loops: `bun test` **691/691 green** (было 682), `bunx tsc --noEmit` clean, `bun run lint`
0 problems. `any`, `@ts-ignore` и `@ts-expect-error` в новом коде — ноль. Бэкенд того же сеанса:
pytest 585/585, `ruff`, `mypy --strict`, одна голова Alembic `d5a7c9e1f3b6`. `make check` целиком
не прогонялся: его цель `test` поднимает постгрес в docker, а демон на машине не отвечает.
---

## 2026-08-30 — PHASE-03/109: вход по ключу, дальше — кука

Тикет: ключ вводится один раз на `/login`, обменивается на `HttpOnly`-куку и в браузере не
хранится нигде. Затронуто 9 файлов (5 new, 4 mod) плюс `package.json`, `Dockerfile` и `Makefile`.

- `lib/auth.ts` — **new** (+тест): `LOGIN_PATH`, `isSafeReturnPath`, `loginHref`, `afterLoginHref`,
  `shouldRedirectToLogin`, `loginRedirectTarget`. Возврат после входа отфильтрован от открытого
  редиректа: `//evil.example` браузер читает как абсолютный URL, поэтому проверки на ведущий слэш
  мало, и без второго условия человек с только что введённым ключом уезжал бы на чужой сайт.
- `lib/api.ts` — **mod**: у каждого запроса `credentials: 'include'`; 401 уводит на `/login`
  жёсткой навигацией (экран не смог загрузить данные — вместе с ним обязано уехать и всё состояние
  хуков), кроме самого `/login`, где 401 значит «ключ не тот» и обязан остаться сообщением формы.
  Добавлен `authAPI` (`login`, `status`, `logout`) и тип `SessionState`. Заголовок `X-API-Key`
  фронтенд не слал и раньше — снимать было нечего.
- `app/login/page.tsx` — **new**: форма с полем `type="password"`, `autoComplete="off"`. Ключ живёт
  в состоянии одного компонента до отправки и стирается сразу после — ни в `localStorage`, ни в
  URL он не попадает. `useSearchParams` обёрнут в `Suspense`, иначе маршрут перестаёт быть
  статическим.
- `components/LogoutButton.tsx` — **new**: «Выйти» одной кнопкой для обеих шкур. Куку стирает
  сервер, поэтому провал `DELETE` не проглатывается: сессия жива, и притвориться вышедшим значит
  соврать.
- `components/AppShell.tsx` — **mod**: `/login` рисуется без навигации — меню, ведущее на экраны,
  которые все отвечают 401, хуже отсутствующего меню.
- `components/Navigation.tsx`, `components/mobile/MoreSheet.tsx` — **mod**: «Выйти» справа в
  десктопной навигации и последней строкой мобильного «More».
- `lib/bundle-scan.ts` — **new** (+тест): обход дерева и два правила — «файл содержит секрет
  дословно» и «файл читает переменную вида `NEXT_PUBLIC_*KEY/SECRET/TOKEN`». Второе сильнее
  первого: оно не требует ни сборки, ни знания текущего ключа, поэтому гоняется на каждом
  `bun test` и держит инвариант против будущих правок.
- `scripts/check-bundle.ts` — **new** + `package.json` script `check:bundle` + цель `front-check`
  в `habit-tracker/Makefile`: `bun run build && bun run check:bundle <ключ>` роняется, если ключ
  найден в `.next`, и роняется так же, если `.next` нет — проверка, молча зеленеющая, когда
  смотреть не на что, хуже отсутствующей. Само значение ключа в вывод не печатается: он уходит в
  логи CI.
- `Dockerfile` — **mod**: комментарий, почему в сборочном слое нет и не будет переменной с ключом.

Feedback loops: `bun test` **704/704 green** (было 682), `bunx tsc --noEmit` clean, `bun run lint`
0 problems, `make front-check API_KEY=<тестовый>` — сборка и `check-bundle: no key in .next`.
Проверено обратной пробой: тот же скрипт на строке, которая в бандле действительно есть, находит
её в 15 файлах и выходит с кодом 1. `any`, `@ts-ignore` и `@ts-expect-error` в новом коде — ноль.

## 2026-08-30 — PHASE-03/134 экран `/roles`

Экран ролей на обоих шеллах: распределение минут за сегодня, акты дня и две формы ручной записи.
Дату экран не считает — `rolesAPI.day()` без аргумента спрашивает сервер, потому что сутки идут
с 04:00 и календарь браузера тут не при чём.

- `lib/plural.ts` — **new**: `countable(count, one, few, many)`. Заведён, чтобы счётного русского
  не стало двух: `streakLabel` в `lib/day-format.ts` переписан на него (**mod**), а не продублирован.
- `lib/role-format.ts` — **new** (+`role-format.test.ts`, 12 тестов): словарь видов актов
  по-русски, `targetShareLine` — целевая доля **никогда** не печатается без слов «гипотеза, не
  норма» (это строка, а не соседняя подпись: подпись можно отлистать от числа), `actsSummary` —
  «Системный архитектор — 1 акт» против «Актов роли сегодня нет».
- `hooks/useRoles.ts` — **new**: чтение дня и справочника, три записи. Каждая запись перечитывает
  день целиком: девяносто минут на найм — не факт про найм, они двигают долю каждой роли в той же
  отрисовке.
- `components/roles/RolesScreen.tsx` — **new** (+`RolesScreen.test.tsx`, 7 тестов): полосы долей,
  список актов, форма минут и форма акта, пометка «вручную» на записи человека и кнопка «убрать».
  Минуты форматируются `formatMinutes` из `lib/day-format` — второй реализации нет.
- `app/roles/page.tsx`, `app/m/roles/page.tsx` — **new**: обе точки входа, один компонент.
- `lib/routes.ts`, `lib/routes.test.ts`, `components/route-icons.ts` — **mod**: экран в реестре под
  «More» (минуты и акты пишутся по концу куска работы, а не десять раз в час), глиф `Gauge`.
- `lib/api.ts` — **mod**: типы ролей и `rolesAPI` — день, справочник, запись и удаление минут и
  актов.

Feedback loops: `bun test` **721/721 green** (было 704), `bunx tsc --noEmit` clean, `bun run lint`
0 problems. `any`, `@ts-ignore`, `@ts-expect-error` в новом коде — ноль.

## 2026-08-30 — PHASE-03/91: время работы на экране дня

- `lib/work-intervals.ts` — **new** (+тест): `momentOf` (настенное `HH:MM` дня → момент со
  смещением машины), `crossesMidnight`, `clockOf`, `spanLabel`, `proposedLabel`, `sourceLabel`,
  строки блока. Какому дню принадлежит интервал, здесь не решается никогда — это ответ сервера.
- `hooks/useWorkIntervals.ts` — **new**: интервалы дня, `add`/`edit`/`remove`, множество
  `saving`. Оптимистичных правок нет намеренно: длину открытого интервала считает сервер
  (до `now`, но не дальше конца суток), и локальная догадка дала бы на экране одно число, а в
  вердикте рядом — другое.
- `components/day/WorkIntervals.tsx` — **new** (+тест, 8 штук): список интервалов с суммой,
  ручной ввод по настенным часам, кнопка «Остановить» у идущего, «Убрать» у любого.
  Исправленный интервал показывает и своё значение, и «Агент предлагал: …». День без интервалов
  говорит «время не измерено», а не «0 ч».
- `components/DayScreen.tsx`, `components/mobile/MobileDayScreen.tsx` — **mod**: блок стоит над
  «Итогом дня», потому что вердикт стоит на его сумме; после любой правки день перечитывается.
- `lib/api.ts` — **mod**: типы `WorkInterval`, `WorkDay`, `WorkIntervalDraft`,
  `WorkIntervalPatch`, `DayDetail.work`; методы `workIntervals`, `addWorkInterval`,
  `updateWorkInterval`, `deleteWorkInterval`. Поля под заголовок окна в типах нет.
- `components/DayScreen.test.tsx`, `hooks/useDay.test.ts` — **mod**: фикстура дня получила блок
  `work` с `work_minutes: null` — честное «не измерено» для дня без интервалов.

Feedback loops: `bun test` **701/701 green** (было 682), `bunx tsc --noEmit` clean,
`bun run lint` 0 problems. `any`, `@ts-ignore`, `@ts-expect-error` в новом коде — ноль.
Бэкенд того же тикета: pytest 603/603, `ruff`, `mypy --strict`, одна голова `d5a7c9e1f3b6`.
`make check` целиком не прогонялся — docker-демон на машине не отвечает.

## 2026-08-30 — PHASE-03/111: экран `/chat`

- `lib/chat-stream.ts` — **new**: чистый разборщик SSE. Состояние здесь неслучайно — сетевой
  кусок кончается там, где решил TCP, регулярно посреди кадра. `ChatStreamEvent` —
  размеченное объединение: `delta`, `usage`, `done`, `error`. Незнакомое имя события и битый
  JSON пропускаются, а не роняют ход.
- `lib/chat-stream.test.ts` — **new**, 12 тестов: порядок кусков, кадр, разрезанный пополам,
  переводы строк внутри ответа, CRLF, `flush` последнего кадра без пустой строки, пропуск
  незнакомого имени и `done` без id.
- `lib/api.ts` — **mod**: типы `ChatConversation`, `ChatMessage`, `ChatConversationDetail` и
  `chatAPI`. `streamMessage` идёт мимо `fetcher`: тот ждёт всё тело, ради отказа от чего ручка
  и существует. `TextDecoder({stream: true})` — то, что не рвёт русскую букву пополам.
- `app/chat/page.tsx` — **new**: лента сообщений, поле ввода, ответ по кускам. Состояния экрана
  и хода — объединения, не булевы флаги. После закрытия хода разговор перечитывается с сервера:
  строки таблицы и есть разговор.
- `lib/routes.ts`, `components/route-icons.ts` — **mod**: экран в реестре под «More», глиф
  `MessagesSquare`. `hasMobile: false` — мобильный близнец это `#118`.
- `lib/routes.test.ts`, `lib/view-mode.test.ts` — **mod**: список «More» пополнился, а
  инвариант «мобильный порт полон» переписан на «полон, кроме перечисленных» и называет `chat`
  поимённо — чтобы следующий экран без близнеца добавляли сюда осознанно, а не мимо теста.

Feedback loops: `bun test` **713/713 green** (было 701), `bunx tsc --noEmit` clean,
`bun run lint` 0 problems. `any`, `@ts-ignore`, `@ts-expect-error` в новом коде — ноль.
Бэкенд того же тикета: pytest 638/638, `ruff`, `mypy --strict`, одна голова `e6b8d0f2a4c7`.
`make check` целиком не прогонялся — docker-демон на машине не отвечает.

## 2026-08-30 — PHASE-03/117 удаление разговора и расход на экране

- `lib/chat-usage.ts` — **new** (+`chat-usage.test.ts`, 8 тестов): `formatTokens`,
  `formatLatency`, `usageSummary`, `turnCost`. Разряды разделяются обычным пробелом, а не
  `toLocaleString`: тот отдаёт неразрывный пробел в одной среде и запятую в другой, и тест на
  строку начал бы зависеть от локали машины. Ноль печатается наравне с остальными числами —
  «расход неизвестен» и «расход нулевой» разные факты. У реплики человека счётчиков нет, и
  строки под ней нет тоже.
- `components/chat/ChatHeader.tsx` — **new** (+`ChatHeader.test.tsx`, 5 тестов): три счётчика,
  медиана и удаление. Подтверждение спрашивается на месте, а не браузерным `confirm`: тот
  непроверяем тестом и не называет, что именно удаление уносит. Вопрос назван целиком —
  «вместе с сообщениями и файлом сессии». Состояние кнопки — union `idle | confirming |
  deleting`, а не пара булевых: во время запроса кнопка недоступна, и второй клик не шлёт
  второй `DELETE`.
- `app/chat/page.tsx` — **mod**: шапка заменена компонентом, расход разговора приезжает тем же
  ответом, что и сообщения (считает его база, второй источник во фронте был бы догадкой), под
  каждым ответом модели — чем обошёлся этот ход. После удаления экран не остаётся на
  разговоре, которого нет: тот же путь, что и при первом заходе.
- `lib/api.ts` — **mod**: тип `ChatUsage`, поле `usage` у `ChatConversation`, `chatAPI.remove`.
  Плюс починка стыка веток: `streamMessage` ходил без `credentials: 'include'` и после `#109`
  отвечал бы 401 в середине разговора.

Feedback loops: `bun test` **765/765 green** (было 752), `bunx tsc --noEmit` clean,
`bun run lint` 0 problems. `any`, `@ts-ignore`, `@ts-expect-error` в новом коде — ноль.

## 2026-08-30 — PHASE-03/113 (раскрывашка «что чат видит»)

Тронуто 4 файла фронта: 3 новых, 2 изменённых.

- `components/chat/ChatContextDisclosure.tsx` — **new**: раскрывашка. Карточка читается по
  первому раскрытию (двадцать тысяч знаков в свёрнутом виде никто не читает), повторное
  раскрытие не перечитывает, текст рисуется моноширинным `<pre>` дословно — пересказ убил бы
  единственный смысл экрана. Состояние — union `idle | loading | failed | ready`.
  Чтение приходит пропсом `load`: подмена модуля `@/lib/api` в bun действует на весь процесс,
  и статический `import { chatAPI }` в компоненте ломал бы соседние наборы тестов.
- `lib/chat-context.ts` — **new**: `sectionLabel`, `sizeSummary`, `truncationNote`. Слова
  пометки об обрезке — решение с тестом, а не разметка внутри JSX. Группировку разрядов даёт
  `formatTokens` из `lib/chat-usage.ts`, второй такой же форматтер разошёлся бы с ним.
- `components/chat/ChatContextDisclosure.test.tsx` — **new**: 4 теста — до раскрытия ничего не
  читается, карточка на экране совпадает с полученной посимвольно, пометка называет выпавшие
  секции по-русски, повторное раскрытие не шлёт второй запрос.
- `lib/api.ts` — **mod**: тип `ChatContext` и `chatAPI.context(id)`.
- `app/chat/page.tsx` — **mod**: раскрывашка под шапкой разговора; `ChatHeader` не тронут —
  он рисует то, что ему дали пропсами, и в сеть не ходит.

Feedback loops: `bun test` **769/769 green** (было 765), `bunx tsc --noEmit` clean,
`bun run lint` 0 problems. `any`, `@ts-ignore`, `@ts-expect-error` в новом коде — ноль.
## 2026-08-30 — PHASE-03/94 (страница `/life` и неделя)

Тикет `94-week-days-endpoint-and-life-page`: `/life` вместо `life.html`, страница недели,
общая боковая навигация. Тронуто 16 файлов фронтенда.

- `lib/life.ts` — **new** (+тест): чистые помощники таймлайна — `dayStatus` (пять состояний,
  из них три главных: выигран / проигран / не закрыт), `lifeCounter` (та же арифметика, что
  считал `life.html`, вплоть до `52.1775` и дефолтов 2000-05-11 / 97 лет), `isoWeekCode`
  по правилу четверга, `groupByYearAndMonth` для боковой навигации.
- `lib/date.ts` — **mod**: `fromISODate` — обратная к `toISODate`. Заведена здесь, а не в
  `lib/life.ts`, чтобы у «строки `YYYY-MM-DD` → Date» остался один ответ на приложение.
- `components/life/DaySquare.tsx` — **new** (+тест): квадрат дня. Три состояния различаются
  заливкой, а не оттенком: выигран — залит лаймом, проигран — залит серым, не закрыт —
  контур с пустой серединой. Сам квадрат — ссылка на `/day/{date}`.
- `components/life/LifeGrid.tsx` — **new** (+тест): пять видов жизнь → год → месяц → неделя →
  день над одним диапазоном дней, счётчик оставшихся недель, рамка жизни в localStorage.
- `components/day/DaySidebar.tsx` — **new** (+тест): боковая навигация год → месяц; раскрыт
  месяц читаемого дня, а не календарный. Один компонент на `/day` и на `/life` — `side.js`
  был вторым списком, и они разъехались.
- `components/week/WeekScreen.tsx` — **new** (+тест): страница недели — выигранные дни, стрик
  на конец, когда сняты счётчики, семь квадратов, чеклист, ретро. Неделя без ретро
  открывается и говорит об этом.
- `hooks/useDays.ts`, `hooks/useWeek.ts` — **new**: один запрос диапазона дней и один — недели.
- `app/life/page.tsx`, `app/m/life/page.tsx`, `app/week/page.tsx`, `app/week/[iso]/page.tsx`,
  `app/m/week/page.tsx`, `app/m/week/[iso]/page.tsx` — **new**: `/m`-пары обоих экранов.
  Голый `/week` — текущая неделя по границе суток сервера, а не по календарю браузера.
- `lib/api.ts` — **mod**: `daysAPI.range`, `weeksAPI` и типы `DayListItem`, `Week`,
  `WeekReviewItem`, `WeekDraft`.
- `lib/routes.ts` + `lib/routes.test.ts`, `components/route-icons.ts` — **mod**: экраны Life и
  Week в реестре, оба под «More».
- `components/DayScreen.tsx` + `components/DayScreen.test.tsx` — **mod**: боковая навигация
  рядом с днём; в тесте замокан `@/hooks/useDays` — `bun` фиксирует имена экспортов при первой
  линковке, и без этого `daysAPI` пропадал для следующего файла.

Feedback loops: `bun test` **711/711 green** (было 685), `bunx tsc --noEmit` clean,
`bunx eslint` 0 problems. `any`, `@ts-ignore`, `@ts-expect-error` в новом коде — ноль.

Долг, названный вслух: боковая навигация скрыта на узких экранах (`hidden lg:block`) — в
мобильном шелле её нет вовсе; редактирование ретро недели из UI не сделано, `PUT /weeks/{iso}`
существует и зовётся только импортом и тестами.

## 2026-08-30 — PHASE-03/121 (быстрая отметка на обоих шеллах)

Тронуто 8 файлов фронта (плюс 24 тестовых файла — в каждом моке `@/lib/api` добавлен
`quickMarksAPI`: `bun` фиксирует имена экспортов при первой линковке, и мок без него удаляет
экспорт для всех следующих файлов).

- `lib/quick-marks.ts` + `lib/quick-marks.test.ts` — **new**: чистое чтение справочника —
  подпись кнопки, свёртка ответа тапа обратно в список (это и есть «один вызов на тап»),
  множество категорий, которые справочник уже закрывает.
- `components/QuickMarkRow.tsx` + `components/QuickMarkRow.test.tsx` — **new**: ряд кнопок.
  Тап отправляет только id кнопки; что она значит — ответ сервера. Пустой справочник рисует
  `null`, а не заглушку.
- `lib/api.ts` — **mod**: `quickMarksAPI` (`list`, `tap`) и типы `QuickMark`, `QuickMarkEvent`,
  `QuickMarkKind`, `QuickMarkSource`, `QuickMarkTap`. Дата в `list` не шлётся: какой день идёт,
  решает сервер.
- `hooks/useToday.ts` + `hooks/useToday.test.ts` — **mod**: справочник в снапшоте Today,
  `tapQuickMark` перерисовывает из ответа тапа и не перезапрашивает список; `nothingToTrack`
  учитывает справочник.
- `app/today/page.tsx` + `app/today/page.test.tsx` (**new**), `app/m/today/page.tsx` +
  `app/m/today/page.test.tsx` — **mod**: секция «Быстрые отметки» первой; категория, у которой
  есть кнопка, теряет старую карточку `QuickNumberRow` — двух путей к одному полю на одном
  экране быть не должно. Категория без кнопки карточку сохраняет, поэтому пустой справочник
  ничего не ломает.

Feedback loops: `bun test` **743/743 green** (было 718), `bunx tsc --noEmit` clean.
`any`, `@ts-ignore`, `@ts-expect-error` в новом коде — ноль.

Долг, названный вслух: хоткеи (#122) не сделаны — колонка `hotkey` приезжает в типах и в
справочнике, клавиатуры на странице нет. `QuickNumberRow` не удалён: справочник заводится
руками и до первой кнопки он пуст.

---

## 2026-08-30 — PHASE-03/142 карта дня на экране дня

Тронуто 7 файлов фронтенда, из них 2 новых.

- `components/day/DayMapCard.tsx` — **new** (+тест): карта дня рядом с планом — жёсткие точки с
  часами из строки правила, свободный вечер интервалом и подписью «не расписывается», вечер с
  близкими, потолки генератора и формула вердикта по порядку. Ни одного числа в вёрстке: новый
  канон двигает карточку без правки фронта.
- `lib/day-format.ts` — **mod**: `edgeLines`, `intervalText`, `relationshipEveningText`,
  `verdictFormulaText`, подпись `EDGE_WITHOUT_A_TIME` для края без часа и метка `anchor_kinds`
  в списке неизмеренного.
- `lib/api.ts` — **mod**: `DayMap`, `DayEdge`, `DayInterval`, `day_map` в `DayDetail`,
  пятнадцать новых полей `DayRuleSet` и `anchor_kinds` в `MissingData`.
- `components/DayScreen.tsx`, `components/mobile/MobileDayScreen.tsx` — **mod**: карточка над
  итогом дня, на мобильном — `compact`.
- `components/DayScreen.test.tsx`, `hooks/useDay.test.ts`, `lib/day-format.test.ts` — **mod**:
  фикстуры дополнены новыми полями правила и блоком `day_map`.

Feedback loops: `bun test` **687/687 green** (было 682), `bunx tsc --noEmit` clean,
`bun run lint` 0 problems. `any`, `@ts-ignore`, `@ts-expect-error` в новом коде — ноль.
## 2026-08-31 — PHASE-03/112 (признак продолжения сессии в шапке чата)

Тикет `112-chat-resume-with-replay-fallback`, фронтовая часть: без неё разница в цене хода
не видна нигде.

- `lib/chat-resume.ts` — **new**: `resumeMode` (размеченное объединение на два состояния, а не
  булев флаг с подписью рядом), `lastCacheRead` — сколько прочитал из кеша последний отвеченный
  ход, `formatTokens`. Четыре условия продолжения браузеру не видны вовсе: ответ приходит одним
  полем `resume_ready` с сервера.
- `lib/chat-resume.test.ts` — **new**, 6 тестов: обе формулировки, «пересбор — не поломка»,
  число берётся у свежего хода, а не у самого дешёвого, пустая лента и разговор без ответа.
- `app/chat/page.tsx` — **mod**: бейдж в шапке плюс строка «прошлый ход прочитал из кеша N
  токенов». `Screen` получил `resumeReady`, и признак пересчитывается после каждого хода —
  файл сессии может исчезнуть между двумя репликами.
- `lib/api.ts` — **mod**: `resume_ready` в `ChatConversationDetail`.

Feedback loops (frontend): `bun test` **780/780 green** (было 774), `bunx tsc --noEmit` clean.
Бэкенд того же тикета: pytest 719/719, `ruff`, `mypy --strict`, одна голова `a8d0c2e4b6f1`.

## 2026-08-31 — PHASE-03/122 (клавиша вместо клика на Today)

Тикет `122-quick-mark-hotkeys-on-today`. Схемы и API он не трогает: `hotkey` уже приехал
с #121 и уже отдаётся в `GET /quick-marks`. Работа целиком фронтовая.

- `lib/quick-mark-hotkeys.ts` — **new**: одна таблица «кнопка → клавиша» (`hotkeyAssignment`),
  из которой читают все трое — обработчик клавиш, подпись на кнопке и легенда, поэтому
  нарисованная клавиша и сработавшая не могут разойтись. `resolveHotkey` отвечает размеченным
  объединением `mark | legend | none`; пять причин молчания — открытый диалог, фокус в поле,
  удержание клавиши, Cmd/Ctrl/Alt и «никто не отзывается». Буква сверяется и по `event.code`:
  без этого `hotkey = 'p'` умирал бы при переключении на кириллицу.
- `lib/quick-mark-hotkeys.test.ts` — **new**, 25 тестов: позиционные цифры, заданная руками
  клавиша, её приоритет над позицией и переживание смены раскладки, INPUT/TEXTAREA/SELECT/contenteditable, Cmd+1, Shift,
  repeat, именованные клавиши, `?` с шифтом и без, пустой справочник.
- `hooks/useQuickMarkHotkeys.ts` — **new**: единственный слушатель `keydown`. Живёт и умирает
  вместе с экраном `/today` — это и есть «на других маршрутах клавиши ничего не отмечают»,
  никакого флага маршрута внутри нет. Мобильная оболочка его не зовёт.
- `hooks/useQuickMarkHotkeys.test.ts` — **new**, 8 тестов, включая `preventDefault` только на
  тех нажатиях, которые обработчик забрал себе, и снятие слушателя при размонтировании.
- `components/HotkeyLegend.tsx` + `.test.tsx` — **new**: лист «клавиша → подпись» по `?`,
  выход по Esc, по крестику и по фону; кнопка без клавиши показана без клавиши.
- `components/QuickMarkRow.tsx` — **mod**: `showHotkeys` печатает `kbd` на кнопке; в
  `aria-label` клавиша не идёт, чтобы объявление кнопки не поменялось.
- `app/today/page.tsx` — **mod**: вызов хука, состояние легенды, кнопка «?» рядом с заголовком
  секции. `dialogOpen` считает открытыми и легенду, и полный редактор записи.

Feedback loops (frontend): `bun test` **822/822 green** (было 780), `bunx tsc --noEmit` clean,
`bun run lint` 0 problems. Бэкенд не тронут, прогнан как контроль: pytest 719/719 в обход
docker через localhost:5432, `ruff`, `ruff format --check`, `mypy --strict`, одна голова
`a8d0c2e4b6f1`. `make check` целиком не прогонялся — docker-демон на машине не отвечает.

## 2026-08-31 — PHASE-03/143, две кнопки закрытия и стадия на экране

Тронуто 8 файлов фронта.

- `lib/api.ts` — **mod**: `ClosingStage`, поля `stage`/`reviewed_at`/`review_skipped` в
  `DaySummary`, тип `DayReviewDraft`; `dayAPI.review` и `dayAPI.closeFinal` с необязательным
  `Idempotency-Key`, старый `dayAPI.close` оставлен синонимом `closeFinal`.
- `lib/day-format.ts` — **mod**: `closingHeadline(stage, verdict)` и строки `VERDICT_LATER`,
  `REVIEW_SKIPPED`. Пустой вердикт значит разное на разных стадиях, и заголовок читается по
  стадии, а не по одному лишь `verdict === null`.
- `lib/day-format.test.ts` — **mod**: тест на все четыре сочетания стадии и вердикта.
- `components/day/DayVerdict.tsx` — **mod**: две кнопки вместо одной («Записать ревью 15:40» /
  «Закрыть день»), заголовок по стадии, строка «ревью в 15:40 не было» на дне, закрытом одним
  касанием. Переопределение вердикта работает как раньше.
- `components/day/DayVerdict.test.tsx` — **mod**, +5 тестов: обе кнопки видны сразу,
  полузакрытый день читается как «вердикт будет вечером» и не как проигрыш, ревью уходит своим
  обработчиком, `review_skipped` сказан вслух и не сказан там, где ревью было.
- `components/DayScreen.tsx`, `components/mobile/MobileDayScreen.tsx` — **mod**: обе оболочки
  зовут `review` и `closeFinal` и перечитывают день после каждого касания.
- `components/DayScreen.test.tsx`, `hooks/useDay.test.ts` — **mod**: заготовки дня получили три
  новых поля итога.

Feedback loops (frontend): `bun test` **828/828 green** (было 822), `bunx tsc --noEmit` clean,
`bun run lint` 0 problems. Бэкенд прогнан как контроль: pytest 737/737 обходом docker,
`ruff`, `ruff format --check`, `mypy --strict`, одна голова `b9e1d3f5a7c2`. `make check`
целиком не прогонялся — docker-демон не отвечает.
  },
## 2026-08-30 — PHASE-03/152 «Экран правил дня»

Тронуто 8 файлов фронта (5 new, 3 mod). `Navigation.tsx` править не пришлось: десктопная
навигация рисуется из `APP_ROUTES`, и экран попал в неё записью в реестре.

- `lib/day-rules.ts` — **new**: черновик новой версии как строки формы, `draftError` (копия
  серверных границ, чтобы 422 не прилетал после нажатия), `draftToPayload` — размеченное
  объединение, payload собирается только из проверенного черновика; `ruleStanding` — прожита /
  действует / выйдет.
- `lib/day-rules.test.ts` — **new**, 26 тестов: процент ↔ десятичная доля, отказ по дате не в
  будущем до всякого запроса, потолок-исключение ниже обычного, ISO-дни, якоря.
- `components/settings/DayRulesScreen.tsx` — **new**: действующая версия целиком (края суток,
  потолки, планка, якоря, свободный вечер — названный вслух как правило плана, колонки под него
  в правиле нет), история версий с датами и пометкой «по этой версии дни уже прожиты», форма
  «новая версия с даты». Рядом с кнопкой публикации — предупреждение, что вердикты прошедших
  дней не изменятся. Форма выводится из канона на каждом рендере, состоянием держится только
  напечатанное: setState в эффекте react-compiler запрещает, а после публикации форма обязана
  отражать уже новую действующую версию.
- `components/settings/DayRulesScreen.test.tsx` — **new**, 11 тестов: правило на экране целиком,
  обе версии с датами, предупреждение — сосед кнопки по DOM (а не «где-то на странице»),
  невозможность правки объяснена текстом, дата не в будущем не уходит в API, отказ сервера
  показывается дословно.
- `hooks/useDayRules.ts` — **new**: одно чтение истории, публикация перечитывает историю целиком
  (публикация — две записи, дописывание показало бы две действующие версии сразу).
- `app/settings/day-rules/page.tsx` — **new**: точка входа.
- `lib/api.ts` — **mod**: `dayRulesAPI` (`getHistory`/`getCurrent`/`publish`), типы
  `DayRuleSetPublish` и `DayRuleSetHistory`. Ни `update`, ни `delete` — их нет и на сервере.
- `lib/routes.ts`, `components/route-icons.ts`, `lib/routes.test.ts`, `lib/view-mode.test.ts` —
  **mod**: экран в реестре под «More», глиф `ScrollText`, `hasMobile: false` назван поимённо в
  тесте мобильного порта.

Feedback loops: `bun test` **750/750 green** (было 713), `bunx tsc --noEmit` clean,
`bun run lint` 0 problems. `any`, `@ts-ignore`, `@ts-expect-error` в новом коде — ноль.
Бэкенд того же тикета: pytest 670/670, `ruff`, `mypy --strict`, одна голова `e6b8d0f2a4c7`.
`make check` целиком не прогонялся — docker-демон на машине не отвечает.
## 2026-08-30 — PHASE-03/92: якоря и тренировка на странице дня

- `components/day/DayAnchors.tsx` — **new**: секция якорей. По строке на каждый вид справочника,
  включая те, по которым ещё ничего не сказано, — «вечера с близкими не было» обязано отличаться
  от «про вечер с близкими не спрашивали». `relationship` стоит в списке наравне с якорями
  здоровья и отмечается тем же кольцом. Кольцо взято из `lib/marks.nextMarkState`, не скопировано:
  `AnchorState` объявлен как `MarkState`, потому что коробка якоря и коробка пункта плана стоят
  одна над другой.
- `components/day/DayTraining.tsx` — **new**: план, факт, минимум (с прямым ответом, есть ли у
  него свой отмечаемый пункт), пропуски подряд, открытая жалоба рядом с предложением, причина у
  каждого снятого движения, личные рекорды с датой и целью.
- `hooks/useTrainingState.ts` — **new**: снимок состояния; ошибка чтения даёт `null`, а не баннер
  поверх дня, который загрузился.
- `lib/api.ts`, `components/DayScreen.tsx`, `components/mobile/MobileDayScreen.tsx` — **mod**.
- `components/day/DayAnchors.test.tsx`, `components/day/DayTraining.test.tsx` — **new** (16 тестов).
- 24 тест-файла — **mod, механически**: в `mock.module('@/lib/api', …)` добавлена заглушка
  `trainingAPI` (bun фиксирует набор экспортов при первой линковке).

Feedback loops (frontend): `bun test` **704/704 green**, `bunx tsc --noEmit` clean.

## 2026-08-30 — PHASE-03/118: чат на мобильном шелле и вход с экрана дня

Срез фронтовый целиком: схемы и ручки чата пришли из `#111`, новых эндпоинтов тикет не заводит.
В этой ветке фронтовая часть `#111` (`app/chat/page.tsx`, `lib/chat-stream.ts`, запись `chat` в
реестре, клиент `chatAPI`) взята из ветки `fast-3` — без неё делать мобильный близнец не из чего.
Бэкенд чата в `fast-2` не переносился: до слияния `fast-3` экран живой, а ручки под ним нет.

- `hooks/useChat.ts` — **new**: состояние разговора на обе оболочки. Разговор из ссылки, иначе
  свежий, иначе заведённый; ход куском за куском; черновик зеркалится в хранилище на каждое
  изменение поля, а не по таймеру — приложение на телефоне сворачивают без предупреждения.
- `components/chat/ChatFeed.tsx`, `components/chat/ChatComposer.tsx` — **new**: лента и поле
  ввода, которые рисуют оба экрана. Поле — не форма и не `submit`: на телефоне оно стоит внутри
  формы `FullScreenSheet`, а вложенная форма — невалидная разметка.
- `components/chat/AskAboutDayButton.tsx` — **new**: «спросить про день». Дата экрана уходит в
  `started_on` явно; маршрут выбирается по текущему пути, чтобы нажатие в `/m/today` не выкинуло
  телефон в десктопную вёрстку.
- `lib/chat-draft.ts` — **new**: черновик по id разговора. Пустой черновик — отсутствующий ключ,
  иначе хранилище копит запись на каждый когда-либо открытый разговор. Отказ хранилища (приватный
  режим Safari) не роняет набор текста.
- `lib/chat-nav.ts` — **new**: `?conversation=<id>`, маршрут чата для текущей оболочки, разбор
  параметра с мусором в `null`.
- `app/m/chat/page.tsx` — **new**: лист на весь экран поверх `FullScreenSheet` — единственная
  причина именно его — слежение за `visualViewport`: иначе поле ввода и последнее сообщение
  уезжают под клавиатуру.
- `app/chat/page.tsx` — **mod**: разметка и ничего больше, вся логика ушла в `useChat`.
- `lib/routes.ts` — **mod**: у чата `hasMobile: true`. Таб-бар не тронут: пять слотов те же.
- `app/today/page.tsx`, `app/m/today/page.tsx`, `lib/api.ts` — **mod**.
- `lib/chat-draft.test.ts`, `lib/chat-nav.test.ts`, `hooks/useChat.test.ts`,
  `components/chat/AskAboutDayButton.test.tsx`, `app/m/chat/page.test.tsx` — **new** (36 тестов).
- `lib/routes.test.ts`, `lib/view-mode.test.ts`, `app/m/today/page.test.tsx` — **mod**: исключение
  «экран без мобильного близнеца» закрыто, регистрация чата и дата из `Today` проверяются.
- 24 тест-файла — **mod, механически**: заглушка `chatAPI` в `mock.module('@/lib/api', …)`.

Feedback loops (frontend): `bun test` **761/761 green**, `bunx tsc --noEmit` clean,
`bun run lint` 0 errors (6 warnings — в чужом `components/day/DayAnchors.test.tsx`).
