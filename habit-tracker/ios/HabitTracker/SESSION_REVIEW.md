# Session Review — iOS HabitTracker

## 2026-07-23 — PHASE-01/11-ios-read-cache

Read-кэш: данные Today и Table видны в авиарежиме с честным баннером, а не белым экраном. Vertical slice — локальная схема (SwiftData) → прозрачная прослойка → VM → UI-баннер → тесты.

- **Schema (local).** `CacheRecord` (`@Model`, `@Attribute(.unique) key`, `payload Data`, `updatedAt`) — одна строка на ключ, снапшот целиком (без точечной инвалидации, см. Out of Scope / #12).
- **Service.** `CacheStore` (протокол save/load Codable + timestamp) с двумя реализациями: `SwiftDataCacheStore` (on-disk, upsert по ключу) и `InMemoryCacheStore` (дефолт в тестах / fallback). `ReadThroughCache` — прозрачная прослойка: успешный ответ перезаписывает кэш и отдаёт `.fresh`; при connectivity-ошибке (`APIClientError.isConnectivity` = timeout/transport) отдаёт `.stale(value, updatedAt)` из кэша, а не бросает. Реальные серверные ошибки (401/500/invalidResponse) стеклом не маскируются — пробрасываются. `ReadCacheLive.shared` собирает on-disk store один раз с in-memory fallback.
- **ViewModel.** `TodayViewModel.load()` кэширует общий `TodaySnapshot` (активные категории + записи + стрики) под `today.snapshot`; `TableViewModel.load()` кэширует окно `TableResponseDTO` под `table.recent`. Оба публикуют `offlineAsOf: Date?` (nil = онлайн). `.live()` обеих VM переведены на общий `EntryMutationLive.makeAPIClient()` + `ReadCacheLive.shared` (дублирующая keychain-обвязка удалена).
- **UI.** `OfflineBanner` — «Offline · showing data from <время>» поверх контента Today и Table, когда `offlineAsOf != nil`.
- **Tests.** 6 тестов `CacheStoreTests` (SwiftData round-trip/overwrite/missing, классификатор connectivity, ReadThrough fresh/stale/rethrow-empty/rethrow-non-connectivity) + по 3 интеграционных теста на Today и Table VM (успех кэширует и остаётся онлайн; авиарежим отдаёт кэш + timestamp свежей VM с мёртвой сетью; без кэша — честный failure). Строгий TDD.

Вся сьюта (143 теста, +12) зелёная на iPhone 17 (iOS 26.3). Сборка app-таргета успешна.

Файлов тронуто: 10 (5 new, 5 mod).

- `HabitTracker/Cache/CacheStore.swift` — new, `CacheStore`/`InMemoryCacheStore`/`ReadThroughCache`/`CacheOutcome`/`APIClientError.isConnectivity`.
- `HabitTracker/Cache/SwiftDataCacheStore.swift` — new, `@Model CacheRecord`, on-disk store + `ReadCacheLive`.
- `HabitTracker/Shared/OfflineBanner.swift` — new, баннер офлайн-данных.
- `HabitTracker/Features/Today/TodayViewModel.swift` — mod, `TodaySnapshot` + load через кэш + `offlineAsOf`, `.live()` на общий фабрике.
- `HabitTracker/Features/Today/TodayView.swift` — mod, баннер поверх контента.
- `HabitTracker/Features/Table/TableViewModel.swift` — mod, load через кэш + `offlineAsOf`, `.live()` на общей фабрике.
- `HabitTracker/Features/Table/TableView.swift` — mod, баннер поверх контента.
- `HabitTrackerTests/CacheStoreTests.swift` — new, 6 тестов кэш-слоя.
- `HabitTrackerTests/TodayViewModelCacheTests.swift` — new, 3 интеграционных теста.
- `HabitTrackerTests/TableViewModelCacheTests.swift` — new, 3 интеграционных теста.

## 2026-07-23 — PHASE-01/37-ios-insights

Раздел Insights: AI-разбор периода с телефона + история отчётов, паритет с бэкенд-эндпоинтами #24/#25. Vertical slice через все слои (DTO/API → VM → UI + вход с Dashboard).

- **DTO/API.** Три новых DTO: `InsightRequestDTO` (period_days), `InsightReportDTO` (id/period_days/content/model/created_at — полный MD-отчёт), `InsightListItemDTO` (метаданные + обрезанный preview). Новый протокол `InsightsAPI` (`fetchInsights` → `GET /insights`, `fetchInsight(id:)` → `GET /insights/{id}`, `createInsight` → `POST /insights`); `APIClient` реализует все три. `EntryMutationLive.makeAPIClient` получил опциональный `timeout` — insights-клиент собирается с щедрым таймаутом (120с), т.к. POST синхронно блокируется на LLM.
- **ViewModel.** `InsightsViewModel`: `load()` тянет историю (`historyState` idle/loading/loaded/failure). `runAnalysis()` шлёт POST по `selectedPeriod` (`InsightPeriod` 7/30/90); при успехе — открывает отчёт и вставляет производную строку в начало истории без reload; 503 → `analysisState = .notConfigured` (честная подсказка), прочие ошибки → `.failure` (ретраится тем же вызовом). `openReport(id:)` тянет полный отчёт в `openedReport`; сбой — в `openErrorMessage`.
- **UI.** `InsightsView`: сегмент-пикер периода + кнопка «Разобрать период» с `NeonLoader` во время анализа; экран-подсказка на 503; `DSErrorState`-ретрай на сбой истории; список прошлых отчётов карточками (тап → детальный шит). `MarkdownText` — лёгкий блочный рендер MD (заголовки/списки/абзацы, инлайн через `AttributedString`) без внешних зависимостей. Вход — новый таб Insights + quick-action на Dashboard.
- **Tests.** 8 новых unit-тестов в `InsightsViewModelTests` (load happy/failure, run happy c проверкой period-payload и вставки в историю, 503→notConfigured, 502→failure→retry успешен, not-configured без API, openReport happy/failure). Строгий TDD (red→green).

Вся сьюта (129 тестов, +8) зелёная на iPhone 17 (iOS 26.3). Сборка app-таргета (вкл. InsightsView) успешна. Живой прогон разбора ждёт `ANTHROPIC_API_KEY` на бэкенде — на моках всё зелёное.

Файлов тронуто: 8 (3 new, 5 mod).

- `HabitTracker/Features/Insights/InsightsViewModel.swift` — new, VM (история + разбор периода + просмотр отчёта).
- `HabitTracker/Features/Insights/InsightsView.swift` — new, UI (пикер+кнопка+лоадер, 503-подсказка, MD-рендер, список истории).
- `HabitTrackerTests/InsightsViewModelTests.swift` — new, 8 unit-тестов + `MockInsightsAPI`.
- `HabitTracker/API/DTOs.swift` — mod, `InsightRequestDTO`/`InsightReportDTO`/`InsightListItemDTO`.
- `HabitTracker/API/APIClient.swift` — mod, протокол `InsightsAPI` + реализация (`fetchInsights`/`fetchInsight`/`createInsight`).
- `HabitTracker/Shared/EntryMutation.swift` — mod, `makeAPIClient(timeout:)` — опциональный таймаут для медленного эндпоинта.
- `HabitTracker/App/HabitTrackerApp.swift` — mod, таб Insights + `AppTab.insights`.
- `HabitTracker/Features/Dashboard/DashboardView.swift` — mod, quick-action «Insights» → таб.

## 2026-07-23 — PHASE-01/38-ios-avoid-streaks

Avoid-стрик карточка «N дней чистый» на экране Today, паритет с web #27/#28. Vertical slice через все слои.

- **DTO/API.** `CategoryDTO` получил поле `streakMode` (значения `avoid`/`build`, дефолт `build` для обратной совместимости со старыми call-site и бэкендами, не отдающими поле) + computed `isAvoid`. Новый `CategoryStreakDTO` (`categoryId`/`streakMode`/`currentStreak`/`bestStreak`/`lastRelapseDate`). Протокол `TodayAPI` расширен `fetchStreak(categoryId:)` → `GET /api/v1/categories/{id}/streak`; `APIClient` реализует метод.
- **ViewModel.** `TodayViewModel.load()` после категорий/записей грузит стрики только для avoid-категорий, конкурентно через `withTaskGroup`; сбой одного стрик-запроса деградирует до «нет карточки» (`try?`), не роняя уже успешный Today. `streaks: [Int: CategoryStreakDTO]` + аксессор `streak(forCategory:)`. Новый `logRelapse(categoryID:count:notes:)`: POST записи с `count` в первое number-поле (по `order`) + опциональная заметка, затем перезагрузка стрика этой категории (current обнуляется, best бэкенд сохраняет). Хелпер `countField(forCategory:)`. Нет number-поля → видимая ошибка, без POST.
- **UI.** `TodayView.row(for:)` разводит avoid-категории (карточка со стриком) и обычные (tap-to-log). `avoidStreakCard`: крупный лаймовый «N days clean» через `DS.Typography.hero`, `Best: M days` ниже, маленькая кнопка «It happened» → `RelapseSheet` (счётчик «сколько» + заметка, focus на счётчике, Save валидирует непустой count). После сохранения sheet закрывается, карточка показывает обнулённый current.
- **Tests.** 4 новых unit-теста в `TodayViewModelTests`: стрик грузится только для avoid, сбой стрика деградирует без падения load, relapse обнуляет current и сохраняет best, relapse без number-поля даёт ошибку.

Вся сьюта (121 тест, +4) зелёная на iPhone 17 Pro (iOS 26.3). Сборка app-таргета успешна.

Файлов тронуто: 5 (0 new, 5 mod).

- `HabitTracker/API/DTOs.swift` — mod, `CategoryDTO.streakMode`/`isAvoid` + `CategoryStreakDTO`.
- `HabitTracker/API/APIClient.swift` — mod, `TodayAPI.fetchStreak` + реализация `GET /categories/{id}/streak`.
- `HabitTracker/Features/Today/TodayViewModel.swift` — mod, загрузка стриков + `logRelapse`/`countField`/`streak(forCategory:)`.
- `HabitTracker/Features/Today/TodayView.swift` — mod, avoid-стрик карточка + `RelapseSheet`.
- `HabitTrackerTests/TodayViewModelTests.swift` — mod, 4 стрик/relapse-теста + mock `fetchStreak`.

## 2026-07-23 — PHASE-01/36-ios-category-charts

Графики на экране категории через Swift Charts, паритет с web `lib/chart-data.ts` / `chart-utils.ts`. Вся доменная логика вынесена в чистый, UI-free модуль `CategoryChart` (enum-namespace): серии по number/time-полям с юнитами и распределением по двум осям (первый юнит — левая ось, остальные — правая), парсинг агрегированных ячеек (`time` → минуты), per-day точки с null-гэпами, кумулятивная свёртка (running sum, null не ломает тотал, вход не мутируется), checklist-бары «X из N» и per-field стрики (сегодня-pending как в вебе), нарезка по периодам 7/30/90/all и годовое окно фетча `GET /table`. Модуль покрыт 24 unit-тестами в паритете с web-тестами.

`CategoryDetailViewModel` расширен: `load()` теперь помимо истории записей тянет агрегированную таблицу (`GET /table` за год, сортировка по возрастанию даты) — сбой таблицы не роняет экран (график вторичен), лог без PII. Добавлены `@Published selectedPeriod`/`chartMode` и computed `chartSeries`/`linePoints`/`isChecklistChart`/`checklistBarPoints`/`fieldStreaks`; период нарезается до свёртки, поэтому кумулята стартует с нуля внутри окна. `CategoryDetailAPI` дополнен `fetchTable` (уже реализован в `APIClient` через `TableAPI`). UI `CategoryChartView`: сегмент-пикеры Period и Per day | Cumulative, мультилинии с легендой (`chartForegroundStyleScale`) для number/time-категорий; для checklist — лаймовый bar «X из N» + горизонтальная лента бейджей стриков. Стиль Lime Tech (лайм на тёмном).

Осознанное ослабление: две оси показаны как две линии с общей осью Y (истинный dual-axis в Swift Charts дорог); легенда/цвета/юниты различают серии. Анимация «дорисовки» — вне скоупа по тикету.

Вся сьюта (117 тестов, +27 к прошлым 90) зелёная на iPhone 17 (iOS 26.3). Сборка app-таргета (вкл. Swift Charts view) успешна.

Файлов тронуто: 7 (3 new, 4 mod).

- `HabitTracker/Features/Categories/CategoryChartData.swift` — new, чистый модуль `CategoryChart` + модели (`ChartPeriod`/`ChartMode`/`ChartAxis`/`ChartSeries`/`ChartPoint`/`ChecklistBarPoint`).
- `HabitTracker/Features/Categories/CategoryChartView.swift` — new, Swift Charts UI (линии+легенда+тогглы / bar+стрики).
- `HabitTrackerTests/CategoryChartDataTests.swift` — new, 24 unit-теста паритета с web.
- `HabitTracker/Features/Categories/CategoryDetailViewModel.swift` — mod, загрузка таблицы + chart-состояние (период/режим/серии/бары/стрики).
- `HabitTracker/Features/Categories/CategoryDetailView.swift` — mod, секция Chart с `CategoryChartView`.
- `HabitTracker/API/APIClient.swift` — mod, `fetchTable` в протоколе `CategoryDetailAPI`.
- `HabitTrackerTests/CategoryDetailViewModelTests.swift` — mod, `MockCategoryDetailAPI.fetchTable` + 3 chart-теста.

## 2026-07-23 — PHASE-01/35-ios-category-detail (round 2, правки по ревью)

Ответ на замечание round 1 о дублировании между `CategoryDetailViewModel`/`CategoryEntryEditView` и `EntriesViewModel`/`EntryEditView`.

- **Общий entry-mutation surface вынесен в `HabitTracker/Shared/EntryMutation.swift`.** Модели `EntryEditDraft`, `EntryLoadState`, `EntryDayGroup` промоутнуты из файлов Entries-фичи в общую локацию. Протокол `EntryMutating` (+ protocol extension) даёт обеим VM единожды: `groupedByDate`, `beginEditing`/`cancelEditing`/`saveEdit`/`deleteEditEntry`/`requireAPI` и `notConfiguredMessage`. Фильтр Entries сохранён через требование `groupableEntries` (дефолт — `entries`, у `EntriesViewModel` — `filteredEntries`). Фабрика live-`APIClient` (парсинг base URL + Keychain + 401-fallback) вынесена в `EntryMutationLive.makeAPIClient()`, оба `live()` теперь тонкие обёртки. `deleteEntry(id:)` переименован в `deleteEditEntry(id:)` (VM-метод больше не совпадает по имени с API-методом); вызовы в обоих View и тестах обновлены.
- **Вью-дубликат устранён.** `CategoryEntryEditView` удалён; `EntryEditView` обобщён в `EntryEditView<Model: EntryMutating>` (в `HabitTracker/Shared/EntryEditView.swift`) и переиспользуется обоими экранами — поля формы приходят параметром `fields` от вызывающего (Entries резолвит из `categories`, detail — из `category.fields`), так форма развязана с раскладкой хранения категорий. `EntrySummary` промоутнут туда же (Components).
- **`CategoryDetailAPI` свёрнут в общий контракт.** Введён базовый `EntryMutationAPI` (fetchEntries/updateEntry/deleteEntry); `EntriesAPI` рефайнит его добавляя `fetchCategories`, `CategoryDetailAPI` — добавляя `createEntry`. Пятой параллельной копии сигнатур больше нет; `APIClient` уже реализует всё.
- **Паритет шапки экрана с web #22/#29 — осознанный скоуп-каст, не пропуск.** `CategoryDetailView` показывает цвет/имя/кол-во полей категории; группа и стрик из веб-шапки опущены сознательно: их нет в `CategoryDTO` (бэкенд их в этот DTO не отдаёт), тянуть их — отдельный слайс схемы/API вне тикета 35. Стрик-карточки идут отдельным тикетом (#38). Зафиксировано и в теле тикета.

Файлов тронуто в round 2: 9 (2 new, 7 mod). Вся сьюта (90 тестов) зелёная на iPhone 17 (iOS 26.3); поведение VM без изменений — те же тесты, что и в round 1.

- `HabitTracker/Shared/EntryMutation.swift` — new, модели + `EntryMutating` protocol/extension + `EntryMutationLive`.
- `HabitTracker/Shared/EntryEditView.swift` — new, generic `EntryEditView` + `EntrySummary`.
- `HabitTracker/API/APIClient.swift` — mod, базовый `EntryMutationAPI`, рефайны `EntriesAPI`/`CategoryDetailAPI`.
- `HabitTracker/Features/Entries/EntriesViewModel.swift` — mod, конформит `EntryMutating`, оставлен только фильтр + load + live-обёртка.
- `HabitTracker/Features/Entries/EntriesView.swift` — mod, локальные `EntryEditView`/`EntrySummary` удалены, шит зовёт общий `EntryEditView`.
- `HabitTracker/Features/Categories/CategoryDetailViewModel.swift` — mod, конформит `EntryMutating`, оставлены quickAdd + форматирование дат + серверный скоуп по категории.
- `HabitTracker/Features/Categories/CategoryDetailView.swift` — mod, `CategoryEntryEditView` удалён, шит зовёт общий `EntryEditView`.
- `HabitTrackerTests/EntriesViewModelTests.swift` — mod, `deleteEntry` → `deleteEditEntry` в вызовах VM.
- `HabitTrackerTests/CategoryDetailViewModelTests.swift` — mod, `deleteEntry` → `deleteEditEntry` в вызовах VM.

## 2026-07-23 — PHASE-01/35-ios-category-detail

Экран одной категории: тап по карточке в списке Categories открывает детальный экран с историей значений, быстрым добавлением и правкой/удалением записей (паритет с web #22/#29). Новый `CategoryDetailViewModel` переиспользует логику `EntriesViewModel` (группировка по датам desc, `EntryEditDraft`, PATCH/DELETE с in-place обновлением списка), но скоупится на одну категорию: `load()` тянет `GET /entries?category_id=<id>` (серверная фильтрация), `quickAdd()` пишет значение первого поля категории (по `order`) сегодняшней датой через generic `POST /entries` и вставляет запись в начало списка без перезагрузки. Пустое значение — no-op; сетевая ошибка сохраняет ввод и показывает сообщение. Дата инъектируется (`now`/`timeZone`) как в `TodayViewModel`. Введён протокол `CategoryDetailAPI` (fetchEntries/createEntry/updateEntry/deleteEntry), `APIClient` уже реализует все методы — добавлено только соответствие. Навигация: строки списка Categories переведены с `Button`(edit) на `NavigationLink` → детальный экран; редактирование категории переехало на leading-swipe, удаление осталось на trailing-swipe. Out of scope (по тикету): графики (#36), avoid-стрик карточки (#38); группа/стрик в шапке опущены — их нет в `CategoryDTO`. 10 новых unit-тестов (90 всего) зелёные на iPhone 17.

Файлов тронуто: 5 (3 new, 2 mod).

- `HabitTracker/Features/Categories/CategoryDetailViewModel.swift` — new, VM детального экрана.
- `HabitTracker/Features/Categories/CategoryDetailView.swift` — new, SwiftUI экран + `CategoryEntryEditView`.
- `HabitTrackerTests/CategoryDetailViewModelTests.swift` — new, 10 unit-тестов (+`MockCategoryDetailAPI`).
- `HabitTracker/API/APIClient.swift` — mod, протокол `CategoryDetailAPI` + соответствие в extension.
- `HabitTracker/Features/Categories/CategoriesView.swift` — mod, `NavigationLink` на детальный экран, edit на leading-swipe; маркер обновлён на ticket 35.

## 2026-07-23 — PHASE-01/32-ios-lime-tech-design-pass (round 2, правки по ревью)

Ответ на замечания ревью первого раунда:

- **Модалки приведены к канону DS.** `QuickEntrySheet` (Today) переработан под дизайн-систему: `presentationDetents([.fraction(0.7), .large])` + drag-indicator, крупное hero-значение первого числового поля через `DS.Typography.hero` (лайм, автосжатие), `dsScreenBackground`, строки секций на `DS.Palette.card`. Остальные compose/edit-формы (`CategoryFormView`, `JournalComposeView`, `EntryEditView`) доведены до того же канона Form, что и `SettingsView`: `dsScreenBackground` + `listRowBackground(DS.Palette.card)` на каждой секции. Логика/биндинги/сохранение не тронуты — правки чисто стилевые, вся сьюта осталась зелёной.
- **Захардкоженный `.foregroundStyle(.red)` заменён на `DS.Palette.danger`** во всех error-строках модалок: `TodayView` (footer required + saveError), `JournalView`, `EntriesView`, `CategoriesView`.
- **Магическое число `64` в футере таблицы** вынесено в `TableView.Metrics.loaderFooterHeight`, рядом с остальными размерами.
- **Мёртвый `Chip` удалён** из `DesignSystem.swift`: экрана чек-листа нет, привязывать не к чему; вернётся вместе с экраном. `DS.Typography.hero` теперь используется (`QuickEntrySheet`), токен оставлен.
- **Иконка приложения** и **полный набор скриншотов 7 табов** — вынесены в Out of Scope / согласованное ослабление (см. тикет 32, раздел «Уточнения round 2»): нет asset-каталога в проекте; per-tab скриншоты упираются в permission-стену GUI-автоматизации симулятора в headless-окружении.

Файлов тронуто в round 2: 6 (0 new, 6 mod) — `DesignSystem.swift`, `Today/TodayView.swift`, `Categories/CategoriesView.swift`, `Journal/JournalView.swift`, `Entries/EntriesView.swift`, `Table/TableView.swift`. Сборка + вся сьюта (80 тестов) зелёные на iPhone 17 (iOS 26.3).

## 2026-07-23 — PHASE-01/32-ios-lime-tech-design-pass

Дизайн-пасс «Lime Tech» по всем экранам. Дизайн-система (`DesignSystem.swift`: токены палитры/радиусов/spacing/типографики + общие компоненты `Card`, `LimeButtonStyle`, `Chip`, `NeonLoader`, `DSErrorState`, `DSEmptyState`, модификатор `dsScreenBackground`) и глобальная тёмная тема с лаймовым акцентом (`HabitTrackerApp`: `preferredColorScheme(.dark)`, `tint(lime)`, `UITabBar`/`UINavigationBar` appearance в near-black + лайм на активном табе) уже были заложены в этой же сессии для Today/Dashboard/Table. Этот проход довёл до канона оставшиеся экраны и привёл состояния к единому идиому: дефолтные `ProgressView("Loading…")` → `NeonLoader`, самодельные error-VStack → `DSErrorState` с лаймовой Retry, `ContentUnavailableView` → `DSEmptyState`, строки списков — на `DS.Palette.card` через `listRowBackground`, типографика/цвета — из токенов, теги журнала и заполненные ячейки таблицы подсвечены лаймом. Логика экранов не тронута. Вся сьюта (80 тестов, вкл. `DesignSystemTests`) зелёная на iPhone 17 (iOS 26.3). Скриншот Dashboard с живого бэкенда приложен к отчёту (тёмный фон, лайм-KPI, крупный H1, лайм-таб); полный набор скриншотов по всем 7 табам headless снять не удалось — переключение табов требует GUI-автоматизации симулятора, упирающейся в permission-стену окружения.

Файлов тронуто: 6 (0 new, 6 mod). `DesignSystem.swift` и `HabitTrackerApp.swift` уже помечены ticket 32 в предыдущих проходах этой сессии.

- `HabitTracker/Features/Table/TableView.swift` — mod, `dsScreenBackground` + `NeonLoader`/`DSErrorState`, лайм-подсветка заполненных ячеек, токены в header/row, `NeonLoader`/`LimeButtonStyle` в футере и деталь-шите.
- `HabitTracker/Features/Categories/CategoriesView.swift` — mod, `NeonLoader`/`DSErrorState`/`DSEmptyState`, card-строки списка, токены; маркер обновлён на ticket 32.
- `HabitTracker/Features/Journal/JournalView.swift` — mod, `NeonLoader`/`DSErrorState`/`DSEmptyState`, card-строки ленты, лайм-теги; маркер обновлён на ticket 32.
- `HabitTracker/Features/Entries/EntriesView.swift` — mod, `NeonLoader`/`DSErrorState`/`DSEmptyState`, card-строки секций; маркер обновлён на ticket 32.
- `HabitTracker/Features/Settings/SettingsView.swift` — mod, `dsScreenBackground`, card-строки формы, лайм-акцент кнопки, статус-индикатор на DS-цветах; маркер обновлён на ticket 32.
- `HabitTracker/Features/Today/TodayView.swift`, `Dashboard/DashboardView.swift` — уже приведены к канону ранее в этой сессии (ticket 32).

## 2026-07-23 — PHASE-01/10-ios-dashboard

Экран Dashboard: стартовый таб с паритетом веб-дашборда — счётчики категорий/записей/журнала и лента последней активности. `DashboardViewModel` грузит три существующих list-endpoint параллельно (`async let`: `GET /categories`, `GET /entries` без фильтра, `GET /journal`) и агрегирует их чистым статик-методом `aggregate(categories:entries:journalTotal:)` в `Stats` (три счётчика + `recentEntries`). Recent-лента сортируется от новых к старым (дата desc, id desc на равных датах) и обрезается до `recentEntriesLimit = 5`. Отдельного stats-endpoint не заводим (объёмы одного пользователя позволяют) — как и предписывает тикет. Журнальный счётчик берёт `total` из ответа: в `APIClient` добавлен `fetchJournalList() -> JournalListResponseDTO`, а прежний `fetchJournalEntries()` теперь тонкая обёртка над ним (без дублирования пути). UI: `List` с секциями Overview (счётчики), Recent activity (записи или «Nothing here yet») и Quick actions (переходы на Today/Journal). Навигация между табами — программное переключение через `TabView(selection:)` и enum `AppTab`; Dashboard — стартовый таб, отдаёт замыкание `onNavigate`. Приёмка: те же счётчики и активность, что и на вебе. 4 новых unit-теста (77 всего) зелёные на iPhone 17.

Файлов тронуто: 5 (3 new, 2 mod).

- `HabitTracker/Features/Dashboard/DashboardViewModel.swift` — new, параллельный load трёх endpoint + чистая агрегация `Stats`, apiProvider из Settings.
- `HabitTracker/Features/Dashboard/DashboardView.swift` — new, секционный список (счётчики + лента + quick actions) с pull-to-refresh, `onNavigate` в другие табы.
- `HabitTrackerTests/DashboardViewModelTests.swift` — new, 4 теста (агрегация счётчиков + фильтр nil, recent newest-first+cap, ошибка сети, not-configured).
- `HabitTracker/API/APIClient.swift` — mod, протокол `DashboardAPI` + `fetchJournalList()` (реюз в `fetchJournalEntries`).
- `HabitTracker/App/HabitTrackerApp.swift` — mod, enum `AppTab` + `TabView(selection:)`, Dashboard как стартовый таб.

## 2026-07-23 — PHASE-01/09-ios-journal

Экран Journal: дневник «как прошёл день» с телефона. `JournalViewModel` грузит ленту (`GET /api/v1/journal`, распаковывает `items` из `JournalListResponseDTO`) и сортирует от новых к старым (по дате, затем по id). Черновик записи живёт в published-полях (`draftTitle`/`draftContent`/`draftDate`/`draftMood`/`draftTags`); `createEntry` требует непустой `content` (иначе ошибка без похода в сеть), опускает пустые title/tags/mood, нормализует теги и шлёт `POST /journal`, вставляя результат в начало ленты; при сетевой ошибке черновик НЕ сбрасывается. Удаление — `DELETE /journal/{id}` с обновлением ленты. Ядро парсинга тегов вынесено в чистый `JournalTags` (`parse`/`normalize`): строка «работа, достижения ,, проект » → `работа,достижения,проект`, пустой ввод → nil. `JournalMood` — enum опций настроения с эмодзи-лейблами, raw-value совпадают со строками бэкенда. UI: лента (дата, настроение, заголовок, превью текста на 3 строки, теги-чипы), compose-шит (title, дата, пикер настроения, многострочный текст, теги через запятую), свайп-удаление с `confirmationDialog`. Новый таб Journal в `TabView`. Приёмка: запись «как прошёл день» с настроением создаётся с телефона (`POST /journal`) и видна в веб-админке. 11 новых unit-тестов (73 всего) зелёные на iPhone 17.

Файлов тронуто: 6 (3 new, 3 mod).

- `HabitTracker/Features/Journal/JournalViewModel.swift` — new, load ленты + compose-черновик + create с нормализацией тегов + delete, `JournalTags`/`JournalMood`, apiProvider из Settings.
- `HabitTracker/Features/Journal/JournalView.swift` — new, лента записей + compose-шит (пикер настроения, теги) + свайп-удаление с confirmationDialog.
- `HabitTrackerTests/JournalViewModelTests.swift` — new, 11 тестов (парсинг/нормализация тегов, load happy+failure, create с настроением+тегами / пропуск пустых полей / пустой content / ошибка сохраняет драфт, delete happy+failure).
- `HabitTracker/API/DTOs.swift` — mod, `JournalEntryDTO`/`JournalListResponseDTO`/`JournalEntryCreateDTO`/`JournalEntryUpdateDTO`.
- `HabitTracker/API/APIClient.swift` — mod, протокол `JournalAPI` + реализация (`fetchJournalEntries`/`createJournalEntry`/`updateJournalEntry`/`deleteJournalEntry`).
- `HabitTracker/App/HabitTrackerApp.swift` — mod, таб Journal в TabView.

## 2026-07-23 — PHASE-01/08-ios-entries-crud

Экран History: история записей списком по датам с правкой и удалением целиком с телефона. `EntriesViewModel` грузит категории (для имён полей/фильтра) и всю историю записей (`GET /api/v1/entries`) одним проходом; список фильтруется по категории (`selectedCategoryId`, `filteredEntries`) и группируется по дню от новых к старым (`groupedByDate`). Правка живёт в `editDraft` (значения полей keyed by field id + заметка): `beginEditing` сеет драфт из записи, `saveEdit` шлёт `PATCH /entries/{id}` и заменяет строку в списке; ключевое свойство — при сетевой ошибке драфт НЕ сбрасывается, поэтому введённые значения не теряются (покрыто тестом). Удаление — `DELETE /entries/{id}` с обновлением списка и `confirmationDialog` в UI. UI: секционный список по датам, меню-фильтр по категориям в тулбаре, свайп-удаление с подтверждением, форма правки (поле на каждый field категории + notes). Новый таб History в `TabView`. Приёмка: опечатка «422 отжимания» правится на «42» за пару тапов (тап по записи → правка значения → Save). 10 новых unit-тестов (62 всего) зелёные на iPhone 17.

Файлов тронуто: 6 (3 new, 3 mod).

- `HabitTracker/Features/Entries/EntriesViewModel.swift` — new, load + фильтр + группировка по датам + edit-draft state machine (PATCH) + delete, apiProvider из Settings.
- `HabitTracker/Features/Entries/EntriesView.swift` — new, секционный список по датам + меню-фильтр + свайп-удаление с confirmationDialog + форма правки значений/заметки.
- `HabitTrackerTests/EntriesViewModelTests.swift` — new, 10 тестов (load, фильтр по категории, сортировка дней, правка опечатки/заметки, ошибка сети сохраняет драфт, delete happy+failure).
- `HabitTracker/API/DTOs.swift` — mod, `EntryDTO.notes`, `EntryUpdateDTO` (PATCH payload).
- `HabitTracker/API/APIClient.swift` — mod, протокол `EntriesAPI` + реализация (`fetchEntries(categoryId:)`, `updateEntry`, `deleteEntry`).
- `HabitTracker/App/HabitTrackerApp.swift` — mod, таб History в TabView.

## 2026-07-23 — PHASE-01/07-ios-categories-crud

Экран Categories: управление категориями и их полями целиком с телефона. `CategoriesViewModel` грузит `GET /api/v1/categories`, создаёт (`POST`), редактирует базовые свойства (`PATCH`) и удаляет (`DELETE`) категории; локальный список обновляется без перезагрузки. Ядро — чистая валидация драфта (`validate(_:)`): пустое имя категории и `select`-поле без непустых опций отклоняются до похода в сеть. Опции `select` сериализуются в JSON-массив-строку бэкенда только при сборке payload — редактор оперирует `[String]`. UI: список с цветными свотчами, форма создания с редактором полей (имя, тип, required, опции), правка базовых свойств, свайп-удаление с `confirmationDialog`. Новый таб Categories в `TabView`. Приёмка: «Приседания» с числовым полем создаётся одним запросом и появляется в Today после его загрузки. 13 новых unit-тестов (52 всего) зелёные на iPhone 17 Pro (iOS 26.3).

Файлов тронуто: 6 (3 new, 3 mod).

- `HabitTracker/Features/Categories/CategoriesViewModel.swift` — new, драфты + чистая валидация + load/create/update/delete state machine, apiProvider из Settings.
- `HabitTracker/Features/Categories/CategoriesView.swift` — new, список со свотчами + форма с редактором полей + confirmationDialog удаления.
- `HabitTrackerTests/CategoriesViewModelTests.swift` — new, 13 тестов (load, валидация пустого имени / select без опций, create c маппингом payload + JSON-опции, update/delete happy+failure).
- `HabitTracker/API/DTOs.swift` — mod, write-payload DTO (`FieldCreateDTO`/`CategoryCreateDTO`/`CategoryUpdateDTO`), `FieldTypeDTO: Hashable` для Picker.
- `HabitTracker/API/APIClient.swift` — mod, протокол `CategoriesAPI` + реализация (`createCategory`/`updateCategory`/`deleteCategory`/`addField`).
- `HabitTracker/App/HabitTrackerApp.swift` — mod, таб Categories в TabView.

## 2026-07-23 — PHASE-01/06-ios-table-view

Экран Table: табличный вид «дни × привычки». `TableViewModel` грузит `GET /api/v1/table` за последние 30 дней (по умолчанию), поддерживает подгрузку более старых страниц (`loadOlder`, мерж по датам без дублей) и достаёт исходные записи ячейки через `GET /entries?category_id&start_date&end_date`. Ядро — чистый маппинг `TableGrid(from: TableResponseDTO)`: колонка = категория (через primary field), строка = день (сортировка по убыванию даты), пустые дни/ячейки → `.empty`. UI: `Grid` с горизонтальным скроллом колонок, тап по непустой ячейке открывает `TableCellDetailSheet` с записями за день, из которых сложилось агрегированное значение. Новый таб Table в `TabView`. 14 новых unit-тестов (39 всего) зелёные на iPhone 17 Pro (iOS 26.2).

Файлов тронуто: 9 (6 new, 3 mod).

- `HabitTracker/Features/Table/TableGrid.swift` — new, чистый маппинг ответа в грид (columns/rows/cells), deep module.
- `HabitTracker/Features/Table/TableViewModel.swift` — new, load/loadOlder state machine + fetchCellEntries, apiProvider из Settings.
- `HabitTracker/Features/Table/TableView.swift` — new, грид с горизонтальным скроллом + детальный шит ячейки.
- `HabitTracker/API/DTOs.swift` — mod, DTO табличного ответа (`TableResponseDTO`/`TableDayDTO`/`TableCellDTO`/`TableCategoryMetaDTO`).
- `HabitTracker/API/APIClient.swift` — mod, протокол `TableAPI` + реализация (`fetchTable`, `fetchEntries(categoryId:date:)`).
- `HabitTracker/App/HabitTrackerApp.swift` — mod, таб Table в TabView.
- `HabitTrackerTests/TableGridMappingTests.swift` — new, 6 тестов маппинга (колонки, пустые дни/ячейки, типы полей, сортировка).
- `HabitTrackerTests/TableViewModelTests.swift` — new, 6 тестов (30-дневный диапазон, пагинация older, ошибки, детали ячейки).
- `HabitTrackerTests/TableAPIClientTests.swift` — new, 2 wire-теста (query `/table`, фильтр `/entries`).

## 2026-07-23 — PHASE-01/05-ios-today-quick-entry (round 2, правки по ревью)

Ответ на замечания ревью первого раунда:

- Checklist-категории больше не идут через generic POST: `saveEntry` ветвится по
  `category.displayMode`, для `checklist` — идемпотентный `PUT /api/v1/entries/checklist`
  (`upsertChecklistEntry` добавлен в протокол `TodayAPI` и `APIClient`; ответ upsert
  заменяет запись в списке по id, без дублей). Покрыто 2 unit-тестами в
  `TodayViewModelTests` + wire-тест PUT в `TodayAPIClientTests`.
- `TodayViewModel.live()`: `try? keychain.read(...)` заменён на явный `do/catch` с
  логированием через `os.Logger` и комментарием-обоснованием (запрос уходит без ключа,
  бэкенд отвечает 401, ошибка видна в UI).
- `QuickEntrySheet`: Save заблокирован, пока не заполнены `isRequired`-поля (футер
  перечисляет незаполненные); `saveErrorMessage` сбрасывается при открытии нового шита;
  boolean-поля сеются значением "false", чтобы состояние тумблера совпадало с payload.
- `FieldDTO.fieldType` — типизированный `FieldTypeDTO` (зеркало backend `FieldType`,
  с `unknown`-кейсом для forward-совместимости); литеральные сравнения в `TodayView`
  убраны. Разбор адреса сервера вынесен в общий `APIClient.makeBaseURL(from:)`
  (используют `TodayViewModel.live()` и `SettingsViewModel.checkConnection`).
- Из changeset вынесены все правки тикета 34 (DURATION): backend + frontend + миграция
  лежат в двух git stash `PHASE-01/34-duration-field-type WIP…`; заведён тикет
  `issues/PHASE-01/backlog/34-duration-field-type.md`.

Файлов тронуто в round 2: 7 (0 new, 7 mod) — `DTOs.swift`, `APIClient.swift`,
`TodayViewModel.swift`, `TodayView.swift`, `SettingsViewModel.swift`,
`TodayViewModelTests.swift`, `TodayAPIClientTests.swift`.

## 2026-07-23 — PHASE-01/05-ios-today-quick-entry

Экран Today: список активных категорий с сегодняшними значениями, тап по привычке открывает динамическую форму по типам полей категории (number → decimal-клавиатура с автофокусом, boolean → toggle, select → picker, text → текстовое поле). Сохранение — `POST /api/v1/entries` с сегодняшней датой; сценарий «42 отжимания» = тап по привычке → ввод числа → Save (2 тапа + ввод). APIClient расширен generic JSON-запросами под `/api/v1` (categories, entries GET/POST, snake_case кодек), маппинг ошибок вынесен в `APIClientError.userMessage`. Навигация — TabView (Today + Settings). 7 новых unit-тестов (22 всего) зелёные на iPhone 17 (iOS 26.3).

Файлов тронуто: 8 (5 new, 3 mod).

- `HabitTracker/API/DTOs.swift` — new, Codable DTO категорий/полей/записей + snake_case coders.
- `HabitTracker/API/APIClient.swift` — mod, generic send/makeAPIURL, `TodayAPI` conformance, `APIClientError.userMessage`.
- `HabitTracker/Features/Today/TodayViewModel.swift` — new, load/saveEntry state machine, apiProvider из Settings.
- `HabitTracker/Features/Today/TodayView.swift` — new, список привычек + QuickEntrySheet (динамическая форма).
- `HabitTracker/App/HabitTrackerApp.swift` — mod, TabView Today/Settings.
- `HabitTracker/Features/Settings/SettingsViewModel.swift` — mod, рефакторинг на `userMessage` (дубликат удалён).
- `HabitTrackerTests/TodayViewModelTests.swift` — new, 4 теста (load success/failure, save success/failure).
- `HabitTrackerTests/TodayAPIClientTests.swift` — new, 3 wire-теста (пути, query, snake_case body).

## 2026-07-23 — PHASE-01/03-ios-scaffold-settings

Скаффолд iOS-приложения: XcodeGen-проект, APIClient (URLSession + async/await, X-API-Key, типизированные ошибки), KeychainStore, экран Settings с проверкой соединения. 15 unit-тестов зелёные (mock URLProtocol + реальный Keychain в hosted-тестах), сборка и запуск проверены в Симуляторе (iPhone 17, iOS 26.3).

Файлов тронуто: 11 (10 new, 1 mod).

- `project.yml` — new, спецификация XcodeGen (app + unit-test bundle).
- `HabitTracker/App/HabitTrackerApp.swift` — new, entry point.
- `HabitTracker/API/APIClient.swift` — new, HTTP-клиент, health-check `GET /`.
- `HabitTracker/API/KeychainStore.swift` — new, хранение API-ключа в Keychain.
- `HabitTracker/Features/Settings/SettingsViewModel.swift` — new, state machine проверки соединения.
- `HabitTracker/Features/Settings/SettingsView.swift` — new, UI Settings.
- `HabitTrackerTests/MockURLProtocol.swift` — new, стаб URLSession.
- `HabitTrackerTests/APIClientTests.swift` — new, 5 тестов (200/401/timeout/500/без ключа).
- `HabitTrackerTests/KeychainStoreTests.swift` — new, 5 тестов round-trip/overwrite/delete.
- `HabitTrackerTests/SettingsViewModelTests.swift` — new, 5 тестов (Keychain-only ключ, state machine).
- `../../.gitignore` — mod, игнор сгенерированного `.xcodeproj`, DerivedData, xcuserdata.

## 2026-07-23 — PHASE-01/12-ios-offline-queue

Оффлайн-очередь для `POST /entries`: запись «42 отжимания» без сети не теряется. SwiftData-модель `PendingEntryRecord` (payload/created_at/attempts/status), протокол `OutboxStore` (in-memory + SwiftData), `OutboxQueue` — enqueue при connectivity-ошибке, flush в порядке enqueue с delete-after-success (запись уходит на сервер ровно один раз, дубликатов нет), авто-флаш по `NWPathMonitor` и при старте приложения. TodayViewModel POST-ит через очередь: оффлайн-сохранение кладётся в outbox и показывается оптимистичной pending-записью + бейдж «N entries waiting to send». Все 151 unit-тест зелёные (8 новых), сборка и тесты прогнаны в Симуляторе (iPhone 17, iOS 26.3).

Файлов тронуто: 5 (2 new, 3 mod) + pbxproj.

- `HabitTracker/Cache/OutboxQueue.swift` — new, PendingEntry-модель, OutboxStore (in-memory + SwiftData), OutboxQueue (enqueue/flush/startAutoFlush), NWPathNetworkMonitor, OutboxLive.
- `HabitTracker/Features/Today/TodayViewModel.swift` — mod, saveEntry POST через outbox при оффлайне, pendingUploadCount, enqueueOffline.
- `HabitTracker/Features/Today/TodayView.swift` — mod, PendingUploadsBadge над списком Today.
- `HabitTrackerTests/OutboxQueueTests.swift` — new, 8 тестов (enqueue→flush, no-duplicate, порядок, connectivity-stop, авто-флаш, SwiftData round-trip, TodayViewModel offline/online).
- `HabitTracker.xcodeproj/project.pbxproj` — mod, регистрация OutboxQueue.swift + OutboxQueueTests.swift.

## 2026-07-23 — PHASE-01/39-server-idempotency-key-entries (iOS wiring)
Файлы: API/APIClient.swift (mod: keyed createEntry overload + Idempotency-Key header), Cache/OutboxQueue.swift (mod: flush передаёт PendingEntry.id.uuidString, доки), HabitTrackerTests/OutboxQueueTests.swift (mod: тест стабильного ключа при replay). Сьюта 153/153.

## 2026-09-05 — PHASE-02/65: чтение Apple Health

Изменено 8 файлов кода и конфигурации: 5 `new`, 3 `mod`.

- `HabitTracker/Features/HealthSync/HealthMetricCatalog.swift` — new: 24 типа и четыре группы.
- `HabitTracker/Features/HealthSync/HealthDataReader.swift` — new: read-only разрешение и чтение каждого типа.
- `HabitTracker/Features/HealthSync/HealthSyncView.swift` — new: запрос при первом входе и явное «Нет данных».
- `HabitTrackerTests/HealthSyncViewModelTests.swift` — new: каталог, один запрос разрешения и чтение всех типов.
- `HabitTracker/App/HabitTrackerApp.swift` — mod: вход в раздел через отдельную вкладку.
- `project.yml`, `HabitTracker/Info.plist`, `HabitTracker/HabitTracker.entitlements` — mod/new: HealthKit capability и описание чтения без разрешения на запись.

## 2026-10-25 — PHASE-01/208: фундамент iOS-порта

Одна фабрика клиента, пять вкладок как в мобильном вебе, подпись под личной командой и цель сборки на телефон. Тронуто 36 файлов: 10 `new`, 26 `mod`.

- `HabitTracker/API/APIClient.swift` — mod: `APIClient.live()` вместо четырёх копий фабрики; помощники запросов и `session` стали `internal` для `APIClient+<Фича>.swift`.
- `HabitTracker/App/AppNavigation.swift` — new: `AppTab` (Today, Day, Chat, Health, More), `MoreDestination`, `AppNavigation.open`.
- `HabitTracker/App/RootView.swift` — new: таб-бар, по одному `NavigationStack` на вкладку, список More с inline-заголовками.
- `HabitTracker/App/HabitTrackerApp.swift` — mod: точка входа рисует `RootView`.
- `HabitTracker/Features/{Day,Chat,QuickMarks,DailySummary}/*View.swift` — new: заглушки «скоро» с `init()` без аргументов.
- `HabitTracker/Features/{Dashboard,Today,Table,Entries,Journal,Categories,Insights,HealthSync,Settings}/*View.swift` — mod: снята внешняя обёртка `NavigationStack`, Dashboard прыгает через `AppDestination`.
- `HabitTracker/Features/{Journal,Dashboard,Categories}/*ViewModel.swift`, `Shared/EntryMutation.swift` — mod: копии фабрики удалены.
- `Cache/OutboxQueue.swift`, `Features/{Insights,Entries,Today,Table}/*ViewModel.swift`, `Features/Categories/CategoryDetailViewModel.swift` — mod: одна строка, вызов `APIClient.live()`.
- `HabitTracker/Features/Settings/SettingsViewModel.swift` — mod: проверка связи через `APIClient.live`, ключи настроек `nonisolated`.
- `project.yml`, `HabitTracker/Info.plist`, `HabitTracker/HabitTracker.entitlements` — mod: `DEVELOPMENT_TEAM`, `CODE_SIGN_STYLE`, строки микрофона, речи и Face ID, фоновая доставка HealthKit.
- `HabitTrackerTests/APIClientLiveTests.swift`, `HabitTrackerTests/AppNavigationTests.swift` — new: 12 тестов фабрики и навигации.
- `../scripts/install-device.sh`, `../../Makefile` — new/mod: `make ios-device`.
- `README.md` — new: правила для тикетов экранов и установка на телефон.

Проверки: `xcodebuild test` на симуляторе iPhone 17 Pro (iOS 26) с подписью симулятора — 168 из 168. С `CODE_SIGNING_ALLOWED=NO` — 152 из 168: 16 тестов Keychain, Settings и `APIClientLiveTests` падают с `-34018`. Глазами на симуляторе: приложение открывается на Today, внизу пять вкладок. Список More и переходы из Dashboard глазами не проверены. Установка на телефон не проверена: `install-device.sh` остановился на шаге «поиск телефона», телефон недоступен.

## 2026-10-25 — PHASE-01/211 (iOS: экран дня и плана)

Файлы (9 new, 1 mod):

- `HabitTracker/API/DTOs+Day.swift` — new: DTO ответа `GET /day` (план деревом, отметки, факты по категориям, итог) и тела запросов.
- `HabitTracker/API/APIClient+Day.swift` — new: `DayAPI` — чтение дня, отметка, факты (POST с `Idempotency-Key`, PUT, DELETE `?mark=unmark`), блокнот, `close/review`, `close/final`.
- `HabitTracker/Features/Day/DayView.swift` — mod: заглушка заменена экраном (`init()` без аргументов): шапка со стрелками дней, план, карточки фактов, итог, блокнот.
- `HabitTracker/Features/Day/DayViewModel.swift` — new: состояние экрана, оптимистичная отметка с откатом, ключи повтора, тихое перечитывание дня после записи.
- `HabitTracker/Features/Day/PlanFactLogic.swift` — new: правила пункта с категорией (разбор «3,5» и «1:30», отметка `done`/`unmark`, тексты прогресса).
- `HabitTracker/Features/Day/DayFormat.swift` — new: окна плана в часовом поясе правила, шаг дня, подписи отметок и вердикта.
- `HabitTrackerTests/{DayAPIClientTests,DayViewModelTests,DayLogicTests,DayFixtures}.swift` — new: 44 теста.

Проверки: `xcodebuild test` на iPhone 17 Pro с подписью симулятора — 212 из 212 (44 новых). Живой бэкенд не поднимался: ответы бэкенда в `DayFixtures` собраны по схемам `DayDetailResponse`, `PlanResponse`, `PlanItemFactsResponse`, `DaySummaryResponse`, а не сняты с работающего сервера.

Не проверено глазами и на телефоне (для #215): вёрстка экрана на симуляторе и телефоне, длинное нажатие на кружок (меню «пропущено»/«снять»), клавиатура с запятой в поле факта, `TextEditor` блокнота под клавиатурой, pull-to-refresh, переход между днями на реальных данных.
Не вошло в порт (есть в мобильном вебе): переопределение вердикта, правка и перенос пунктов плана, якоря, тренировка, интервалы работы, карта дня, отчёт дня, создание плана, диф плана.

## 2026-10-25 — PHASE-01/214: Face ID при входе

Экран блокировки при запуске и после 5 минут в фоне; ключ API в Keychain под `.biometryCurrentSet` (запасной код устройства — выбор в Settings). Тронуто 11 файлов: 6 `new`, 5 `mod`.

- `HabitTracker/App/BiometricAuthenticator.swift` — new: `BiometricAuthenticating`, `BiometricFailure`, `LocalAuthenticator` на `LAContext`.
- `HabitTracker/App/BiometricSession.swift` — new: `KeyProtection`, общий проверенный `LAContext`; без него чтение защищённого ключа молча отказывает, а не поднимает Face ID.
- `HabitTracker/App/LockController.swift` — new: `LockSettings`, `AppLockController` (запуск, фон, таймаут, один запрос за раз).
- `HabitTracker/App/LockScreenView.swift` — new: экран блокировки, `.appLock()`, обложка для app switcher.
- `HabitTracker/App/HabitTrackerApp.swift` — mod: одна строка `.appLock()`.
- `HabitTracker/API/KeychainStore.swift` — mod: `save(protection:)`, `read(context:)`, значения по умолчанию прежние.
- `HabitTracker/Features/Settings/SettingsViewModel.swift`, `SettingsView.swift` — mod: два переключателя, перезапись ключа под новую защиту с откатом, пустое поле не стирает нечитаемый ключ.
- `HabitTrackerTests/{LockControllerTests,BiometricKeyProtectionTests}.swift` — new: 21 тест на подделке `BiometricAuthenticating`.
- `README.md` — mod: строка таблицы про модификатор.

Проверки: `xcodebuild test` на iPhone 17 Pro с подписью симулятора — 189 из 189. Симулятор не навязывает access control Keychain (проба: защищённый ключ читается молчаливым контекстом), поэтому защита ключа проверяется только на телефоне. Глазами на симуляторе (Face ID записан через `notifyutil`): экран блокировки, успешное совпадение открывает Today, несовпадение показывает системный запрос; недоступный Face ID даёт сообщение.

### Круг 2 — PHASE-01/214: исправления проверки

Тронуто 8 файлов, все `mod`: `API/KeychainStore.swift`, `App/LockController.swift`, `App/LockScreenView.swift`, `Features/Settings/SettingsView.swift`, `Features/Settings/SettingsViewModel.swift`, `HabitTrackerTests/{KeychainStoreTests,BiometricKeyProtectionTests,LockControllerTests}.swift`.

- **Перезапись ключа.** `KeychainStore.save` пишет новое значение под `<key>.pending`, удаляет старый элемент, пишет под `<key>` и чистит pending. Сбой до удаления оставляет старый ключ. Сбой последней записи оставляет значение под pending: `read` берёт его, когда основного элемента нет, `delete` стирает оба. Схему с `SecItemUpdate` (переименование) не взял: что защищённый элемент даёт менять атрибуты без Face ID, на симуляторе не проверить. Откат через `try?` убран: старый элемент не пропадает, откатывать нечего. После сбоя `SettingsViewModel` читает ключ проверенным контекстом; если не читается, возвращает открытый ключ в поле `apiKey` и пишет «нажмите «Сохранить»».
- **Шов для тестов.** `KeychainBackend` (три замыкания: `add`, `delete`, `copyData`) передаётся в `KeychainStore.init`, по умолчанию настоящий SecItem. Тестовый `KeychainFaults` ломает нужный шаг поверх настоящего Keychain.
- **Обложка app switcher.** Отдельный `UIWindow` на уровне `.alert + 1` (`PrivacyCoverWindow`), а не закрытие sheet. Причина: `.inactive` приходит и от Центра управления, и от системных окон; закрытие sheet стирало бы ввод без причины. Окно перекрывает sheet, alert и клавиатуру. Экран блокировки остаётся в корне: при блокировке контент уходит из дерева вместе со sheet. На устройстве не проверено: попадает ли окно в снимок app switcher.
- **Предупреждения.** (а) Face ID сам поднимается раз на запуск и раз на возврат из `.background` (`takeActivationPrompt`); после «Отмена» остаётся кнопка «Открыть». (б) Смена запасного кода подтверждается текущей политикой (`lockSettings.allowsPasscode`). (в) Нечитаемый ключ не мешает выключить блокировку: перезаписи нет, под переключателем сообщение «введите заново». Включить блокировку при нечитаемом ключе нельзя.

Для #215 (только записано, не сделано): фоновая отправка HealthKit при запертом телефоне идёт без ключа; несохранённый ввод пропадает при повторной блокировке; при возврате из фона на кадр виден контент до блокировки; проверить на телефоне, что окно-обложка попадает в снимок app switcher и что `SecItemAdd` под pending с `.biometryCurrentSet` не поднимает второй запрос Face ID. Первые два пункта вынесены в текст под переключателем.

Проверки: `xcodebuild test` на iPhone 17 Pro с подписью симулятора — 204 из 204 (+15 тестов круга).
## 2026-10-26 — PHASE-01/210: Today на iOS целиком

Быстрые отметки с отменой и офлайн-очередью, лист подходов и записей за день, Happened одним нажатием, история срывов с графиком. Тронуто 22 файла: 18 `new`, 4 `mod`.

- `HabitTracker/API/APIClient+Today.swift`, `HabitTracker/API/DTOs+Today.swift` — new: справочник быстрых отметок, нажатие под `Idempotency-Key`, отмена, подходы дня, один запрос `/streaks`, срыв, история срывов, patch/delete записи.
- `HabitTracker/Features/QuickMarks/QuickMarksViewModel.swift`, `QuickMarkTapQueue.swift`, `QuickMarkWording.swift`, `QuickMarksSection.swift` — new: кнопки отметок, очередь нажатий без потерь офлайн, формулировки, секция на Today.
- `HabitTracker/Features/QuickMarks/QuickMarkDaySetsViewModel.swift`, `QuickMarkDaySetsSection.swift` — new: подходы за день.
- `HabitTracker/Features/QuickMarks/QuickMarksView.swift` — mod: заглушка заменена экраном.
- `HabitTracker/Features/Today/RelapseAnalysis.swift`, `RelapseHistoryView.swift`, `RelapseHistoryViewModel.swift`, `RelapseDetailsSheet.swift` — new: история срывов, график Swift Charts, анализ по серверной семантике #207.
- `HabitTracker/Features/Today/TodayDaySheet.swift` — new: лист дня категории.
- `HabitTracker/Features/Today/TodayView.swift`, `TodayViewModel.swift` — mod: серии одним `/streaks`, Happened без number-поля, переход на историю срывов; место под кнопку голоса (#213) помечено `TODO(#213)`.
- `HabitTrackerTests/{QuickMarkTapQueueTests,QuickMarksViewModelTests,RelapseAnalysisTests,TodayDetailViewModelsTests,TodayScreenAPITests,TodayViewModelTests}.swift` — new/mod: view model на подделанном `URLProtocol`, офлайн-нажатия, одна выборка серий.

Проверки: `xcodebuild test` на симуляторе av06-iPhone17Pro (iOS 26) с подписью симулятора — 227 из 227. Не проверено: живой бэкенд (охранный хук не пускает миграцию живой базы роя, экран шёл только на подделке API), вёрстка глазами, Face ID, график и анализ срывов на реальных данных, поведение на телефоне (для #215).

## 2026-10-26 — PHASE-01/213: голосом рассказать день на iOS

Экран «Рассказать день»: диктовка или текст, черновик плана, предпросмотр с переключателями, запись выбранного одним `apply`. Тронуто 10 файлов: 8 `new`, 2 `mod`.

- `HabitTracker/API/APIClient+DailySummary.swift`, `HabitTracker/API/DTOs+DailySummary.swift` — new: `draft` и `apply` (с `Idempotency-Key`), операции плана с `source_text` и флагами `uncertain`/`implausible`/`estimated`, журнал с режимом `append`/`create`/`replace`.
- `HabitTracker/Features/DailySummary/DailySummaryViewModel.swift` — new: диктовка в редактируемый текст, черновик за сегодняшнюю дату, сомнительные строки выключены, один ключ на план (повтор после сбоя — та же запись), `replace` только по просьбе и только если за день есть текст.
- `HabitTracker/Features/DailySummary/SpeechDictation.swift` — new: шов `SpeechDictating` и системная реализация на `SFSpeechRecognizer` + `AVAudioEngine`, `requiresOnDeviceRecognition` включается, если распознаватель умеет на устройстве.
- `HabitTracker/Features/DailySummary/DailySummaryView.swift` — mod: заглушка заменена экраном и `VoiceDayButton` (лист с собственным стеком). `DayPlanPreview.swift` — new: карточки плана.
- `HabitTracker/Features/Today/TodayView.swift` — mod: одна строка `VoiceDayButton` на месте `TODO(#213)`, после записи Today читает день заново.
- `HabitTrackerTests/DailySummaryAPIClientTests.swift`, `DailySummaryViewModelTests.swift` — new: формат запросов, диктовка на подделанном распознавателе, отказ в доступе сохраняет набранный текст, до подтверждения на сервер уходит только `draft`.

Проверки: `xcodebuild test` на av09-iPhone17Pro с подписью симулятора — 290 из 290 (+31 тест). Тела запросов сверены с `app/schemas/daily_summary.py` через pydantic (`extra=forbid` у метрики и галки). Не проверено: живой бэкенд (охранный хук не пустил создание живой базы роя с миграцией), вёрстка глазами, всё, что требует телефона — для #215: запросы разрешений на микрофон и речь, звук, сама диктовка, `supportsOnDeviceRecognition` для ru-RU (без него звук уходит в Apple), лимит около минуты на фразу, звонок или смена аудиомаршрута во время диктовки, реальный разбор моделью.

### Круг 2 — PHASE-01/213: исправления проверки

Тронуто 8 файлов: `Features/DailySummary/{SpeechDictation,DailySummaryViewModel,DailySummaryView,DayPlanPreview}.swift`, `API/DTOs+DailySummary.swift` (mod); `HabitTrackerTests/{DailySummaryViewModelTests,DailySummaryAPIClientTests}.swift` (mod), `SystemSpeechRecognizerTests.swift` (new). Перед правками влит `main` (конфликт только в этом файле).

- **Движок и сессия.** `SystemSpeechRecognizer` собран из швов `AudioInput`, `AudioSessionControlling`, `RecognitionBackend`. Tap снимается без условия в `teardown` и перед установкой, звонок или смена маршрута оставляют tap, а второй `installTap` на ту же шину роняет приложение. `stop()` сразу отдаёт аудиосессию (музыка с `.duckOthers` возвращается), а не после финального результата. Звонок (`interruptionNotification`, `began`) и `AVAudioEngineConfigurationChange` завершают поток ошибкой `.interrupted`, экран показывает причину и сохраняет услышанное. Уход приложения из `.active` останавливает диктовку (`stopDictationForBackground`). Закрытие листа во время системного запроса разрешений отзывает старт.
- **День.** Выбор дня — шевроны и «Сегодня» как на экране «День» (#211), а не системный `DatePicker`; вперёд дальше сегодняшнего нельзя. Смена дня даёт новый `Idempotency-Key`, день показан и над предпросмотром плана.
- **Запись без ответа.** После таймаута, обрыва, ошибки сервера или битого ответа запись считается неподтверждённой: строки, режим журнала, день и «Пересобрать план» заморожены до успешного повтора под тем же ключом; кнопка зовётся «Повторить запись». Отказ 400/422/409 ничего не записал: план редактируем, у 409 свой текст. Во время `.applying` всё заблокировано.
- **Отмена разбора.** Кнопка «Отменить» и отмена в `onDisappear`; отмена (`CancellationError`, `URLError.cancelled`, `transport(-999)`) возвращает прежний план или `.idle`, а не «нет связи».
- **Мелочи.** Число в карточке форматирует `formatted(.number)` (прежнее `Int(value)` падало от 1e20). `mode` журнала — enum. При замене заголовок и подпись говорят, что прежний текст пропадёт. Переключатель «Заменить» скрыт при выключенном журнале. «Записать» недоступна, пока идёт диктовка. Повторное «Говорить» во время запроса разрешений игнорируется. Причина сомнения — в `accessibilityHint` строки.
- **Не сделано.** Кнопка голоса на Today видна только при непустом списке категорий: показ в пустом состоянии требует правки Today сверх одной строки, оставлено владельцу #210. Типы плана `LogMetricOpDTO`/`CheckOpDTO`/`JournalOpDTO` дублируют `ChatPlan*DTO` из #212 — объединение вынести в отдельный тикет.

Проверки круга: `xcodebuild test` на av09-iPhone17Pro с подписью симулятора (число — в сдаче). Для #215 добавлено: звонок во время диктовки и повторное «Говорить»; музыка возвращается после закрытия листа; запрос разрешений поверх экрана не отзывает старт.

## 2026-10-26 — PHASE-01/212: чат на iOS с потоковым ответом и историей

Экран чата вместо заглушки #208: лента сообщений, живой пузырь текущего хода, поле ввода, лист истории с удалением разговоров, применение и отклонение плана. Тронут 1 файл `mod`, создано 10 `new`.

- `HabitTracker/API/SSEStream.swift` — new: разбор SSE по байтам; граница кадра — пустая строка, где бы ни оборвался сетевой чанк (в том числе внутри UTF-8 символа); CRLF, комментарии, пустые кадры; хвост без пустой строки отдаёт `flush()`.
- `HabitTracker/API/APIClient+Chat.swift`, `HabitTracker/API/DTOs+Chat.swift` — new: список, создание, чтение, сброс и удаление разговоров, чтение/применение/отклонение плана, один ход как `AsyncThrowingStream` на `URLSession.bytes`; отмена задачи закрывает соединение.
- `HabitTracker/Features/Chat/ChatViewModel.swift` — new: состояние экрана, живой пузырь хода (текст до retrieval отбрасывается, мысли не попадают в ответ), отказы 409/429 текстом, черновик на разговор, удаление (409 при идущем ответе объяснён), повтор применения плана под тем же `Idempotency-Key`.
- `HabitTracker/Features/Chat/ChatView.swift` — mod: заглушка заменена экраном; уход с экрана отменяет ход, сервер оставляет начатое как `interrupted`.
- `HabitTracker/Features/Chat/ChatHistoryView.swift`, `ChatMessageViews.swift`, `ChatPlanCardView.swift` — new: история с подтверждением удаления, пузыри, карточка плана с отметками строк.
- `HabitTrackerTests/{SSEStreamTests,ChatAPIClientTests,ChatViewModelTests}.swift` — new: 13 + 15 + 28 тестов на зафиксированном потоке и подделанном `URLProtocol`; настоящая модель не вызывается.

Проверки: `xcodebuild test` на симуляторе HT212 iPhone 17 Pro с подписью симулятора после слияния main (#208, #210, #214) — 319 из 319. Не проверено: живой бэкенд (охранный хук не пускает живую базу роя, экран шёл только на подделке API); вёрстка и поток глазами; ввод с клавиатурой, прокрутка за растущим пузырём, поведение при блокировке экрана посреди ответа.

Для #215 (только на телефоне): реальный поток по Tailscale (буферизация прокси, обрыв при уходе приложения в фон); прокрутка к низу при длинном ответе; клавиатура и `scrollDismissesKeyboard`; возобновление экрана после блокировки Face ID во время хода.

### PHASE-01/212, круг 2: замечания ревью

Тронуто 5 файлов `mod`: `Features/Chat/{ChatViewModel,ChatView,ChatHistoryView,ChatMessageViews}.swift`, `HabitTrackerTests/ChatViewModelTests.swift`.

- `ChatViewModel.swift` — `historyNotice` стал парой (разговор, причина): «идёт ответ» гаснет, когда ход этого разговора кончился или открыт другой, остальные — на `loadHistory()`; повтор после ошибки открывает тот же разговор (`retry()`); открытый разговор из истории не переоткрывается и не рвёт ответ; токен хода не даёт старой задаче писать в новый ход; `reset()` сверяет разговор после `await`; ответ остаётся на экране, пока перечитывание не удалось; ошибки загрузки и обновления плана видны.
- `ChatView.swift` — `notice` рисуется вне поля ввода (видна в `.empty` и `.failed`), «Повторить» зовёт `retry()`.
- `ChatHistoryView.swift`, `ChatMessageViews.swift` — строка замечания с названием разговора; пузырь без вечного индикатора, когда ответ получен, а копия не прочитана.
- `ChatViewModelTests.swift` — +16 тестов: оба сценария замечания, ошибка «Новый разговор» в `.empty`/`.failed`, повтор, гонки (A→B, старый ход против нового), `reset`, ответ без копии, ошибки плана.

Проверки: `xcodebuild test` на симуляторе HT212 с подписью симулятора — 335 из 335. Не проверено: живой бэкенд (охранный хук), вёрстка строки замечания глазами.
## 2026-10-26 — PHASE-01/211, круг 2 (iOS: экран дня и плана)

Решение владельца: время пунктов плана показывается в часовом поясе устройства (`TimeZone.current`), как мобильный веб (`frontend/lib/time.ts`, приёмка 5.7), а не в `rule.timezone`. Сервер отдаёт UTC-момент; пояс стал параметром `DayFormat.clock/window(in:)`, по умолчанию `.current`.

Файлы (0 new, 6 mod):

- `HabitTracker/Features/Day/DayFormat.swift` — mod: `clock/window(in: TimeZone)` вместо `timeZoneID`; `anchorsHint`.
- `HabitTracker/Features/Day/DayView.swift` — mod: окно плана без `timeZoneID`; подсказка «якоря отмечаются в вебе» над «Закрыть день».
- `HabitTracker/Features/Day/DayViewModel.swift` — mod: черновик блокнота по дню (в памяти) вместо молчаливой потери при смене дня; `saveNotebook` не отмечает чужой день сохранённым.
- `HabitTracker/API/DTOs+Day.swift` — mod: только комментарий к `DayRuleDTO`.
- `HabitTrackerTests/{DayLogicTests,DayViewModelTests,DayFixtures}.swift` — mod: тесты пояса с подменой (Берлин, Нью-Йорк, UTC), таблица done/unmark из `frontend/lib/plan-facts.test.ts` (9 тестов, включая 100→120 при цели 300), три теста черновика блокнота, `DayFixtures.day(date:notebook:)`.

Проверки: `xcodebuild test` на симуляторе av04-iPhone17Pro с подписью симулятора — 321 из 321 после слияния main. Живой бэкенд не поднимался; пункт Acceptance «живая копия бэкенда» остаётся `[ ]` — проверит человек / #215.

Не проверено глазами: подсказка про якоря и возврат черновика блокнота на экране. Известный предел: черновик живёт в памяти и не переживает перезапуск; черновик итога дня (минуты, текст) при смене дня по-прежнему сбрасывается.

## 2026-10-27 — PHASE-03/227: хвосты ревью #213 (iOS, голосовая сводка)

Файлы (0 new, 6 mod):

- `HabitTracker/Features/DailySummary/DailySummaryViewModel.swift` — mod: флаг «запись не подтверждена» снимают только 400/422; 401 и `invalidBaseURL` оставляют его как был (после таймаута план остаётся замороженным), 409 флаг держит; текст 409 «запись по этому плану уже прошла, проверьте день», без совета разобрать заново; русский текст 401/неверного адреса (и для черновика); смена дня сбрасывает готовый план в `.idle`; `generate()` ставит `.loading` с первого нажатия и ждёт финал диктовки внутри отменяемой задачи; `apply()` без адреса сервера пишет ошибку; `closeNeedsConfirmation`.
- `HabitTracker/Features/DailySummary/DailySummaryView.swift` — mod: лист `VoiceDaySheet` владеет view model; свайп отключён, пока запись не подтверждена или идёт; «Закрыть» просит подтверждения.
- `HabitTracker/Features/DailySummary/SpeechDictation.swift` — mod: `interrupt()` молчит после обычной остановки; `AVAudioEngineConfigurationChange` фильтруется по своему движку (`AudioInput.configurationChangeSource`); новый движок на каждую сессию; `mediaServicesWereResetNotification` кончает поток как `.interrupted`; замыкания отмены помечены `@Sendable`.
- `HabitTracker/Features/Today/TodayView.swift` — mod: кнопка «Рассказать день» видна и без категорий.
- `HabitTrackerTests/DailySummaryViewModelTests.swift`, `SystemSpeechRecognizerTests.swift` — mod: +13 тестов, один переписан (таймаут → 401, 401 на первой попытке, 409, смена дня, закрытие листа, двойное «Разобрать», пустой текст после ожидания, `apply` без адреса; чужой движок, сброс медиасервисов, сигнал после остановки).

Не сделано: объединение `LogMetricOpDTO`/`CheckOpDTO`/`JournalOpDTO` с `ChatPlan*DTO` (#212). Типы чата лежат в `API/DTOs+Chat.swift` и сидят в `Features/Chat`; у них нет `op` и `existingEntryId`, `mode` у журнала — строка. Объединение правит чат — отложено до владельца чата.

Свайп листа перехватить с вопросом нельзя без UIKit (`presentationControllerDidAttemptToDismiss`): свайп отключён на время неподтверждённой записи, вопрос задаёт кнопка «Закрыть».

Проверки: `xcodebuild test` на av06-iPhone17Pro с подписью симулятора — 460 из 460 (круг 2). Не проверено: микрофон, звонки, AirPods, вёрстка листа и кнопки на пустом Today, диалог закрытия.

Для #215 (только на телефоне): AirPods (HFP) на первом нажатии «Говорить» — переключение профиля Bluetooth и не потерян ли первый звук; сброс медиасервисов посреди диктовки (сообщение «Диктовка прервалась», следующее «Говорить» работает на новом движке); смена маршрута другого движка (музыка в другом приложении) не рвёт диктовку; диалог закрытия при неподтверждённой записи (авиарежим во время «Записать»); кнопка «Рассказать день» на Today без категорий.

### PHASE-03/227, круг 2: замечания ревью

- `DailySummaryViewModel.swift` — 409 стал конечным состоянием `ApplyState.alreadyApplied` (флаг «не подтверждена» снят, повтор и пересборка закрыты, `onApplied` не зовётся: лист остаётся и говорит об этом); текст 401 после таймаута больше не обещает «дубля не будет»: ключ правится в Settings, туда не попасть, не закрыв экран; смена дня сбрасывает и ошибку черновика.
- `DailySummaryView.swift` — экран разделён: `DailySummaryContent` (`@ObservedObject`) и `DailySummaryView` (вкладка More, владеет моделью, `@StateObject`). Страница More прячет «Назад» при неподтверждённой записи и ставит свою кнопку с тем же диалогом; свайп назад уходит вместе со скрытой кнопкой. `RootView.swift` не правился: `DailySummaryView()` остался тем же вызовом. Карточка `alreadyApplied` с «Рассказать ещё».
- `SpeechDictation.swift` — `AVAudioEngine` создаётся только в `installTap`; `interrupt` сверяет поколение сессии; порядок «observeInterruptions после installTap» закреплён комментарием.
- Тесты: 409 как выход, текст 401, отмена во время ожидания диктовки, ошибка черновика при смене дня; тест пустого текста теперь видит `.loading` во время ожидания.

Известный предел: после 409 Today не перечитывается сам (лист не закрывается и `onApplied` не зовётся); видно после pull-to-refresh. Не проверено на устройстве: скрытая «Назад» действительно отключает свайп назад, диалог и карточка 409 глазами.
## 2026-10-27 — PHASE-03/226: хвосты экрана «День» (iOS)

Тронуто 8 файлов `mod`: `Features/Day/{DayViewModel,DayView,DayFormat}.swift`, `API/DTOs+Day.swift`, `HabitTrackerTests/{DayViewModelTests,DayLogicTests,DayAPIClientTests,DayFixtures}.swift`.

- `DayViewModel.swift` — перечитывание того же дня берёт серверный блокнот, если локально нет несохранённого текста. Черновик хранит серверный текст, на котором набран (`base`). Если сервер с тех пор изменился, текст остаётся на экране, а серверный показан рядом (`notebookConflict`); сохранение закрыто, пока человек не выберет «Оставить мой» или «Взять с сервера». Поля итога дня (минуты, что случилось) уходят в черновик дня так же, как блокнот; нетронутое поле следует за сервером. `rereadInPlace()` перечитывает без лоадера при возврате из фона и `significantTimeChange`; `systemTimeZoneDidChange()` сбрасывает системный пояс и пересчитывает время пунктов. Сохранение блокнота дня A, завершившееся после шага на B, не метит B и стирает свой устаревший черновик. Ошибка сохранения называет день.
- `DayView.swift` — `scenePhase` (из `.background` в `.active`), `significantTimeChangeNotification`, `NSSystemTimeZoneDidChange`; карточка конфликта в блокноте; подсказка про якоря только при `anchorsTotal > 0`; подпись кнопки отметки называет пункт; убран `PlanItemRow.depth`.
- `DayFormat.swift` — форматтеры дат и времени кэшируются (часы — по одному на пояс под замком).
- `DTOs+Day.swift` — `DayRuleDTO.timezone` не декодируется (ответ без него разбирается).

Проверки: `xcodebuild test` на av04-iPhone17Pro с подписью симулятора — 467 из 467 (+20 тестов на Day*). Не проверено: живой бэкенд, вёрстка карточки конфликта и подсказки глазами, повторный вход из фона на устройстве.

Для #215 (только на телефоне):
- Смена пояса: Настройки → Основные → Дата и время → пояс другой; вернуться в приложение: время пунктов плана пересчитано без перезапуска, экран не мигает лоадером.
- Возврат из фона на следующий день: оставить экран «День» открытым на «сегодня», свернуть до полуночи (или сменить дату на устройстве), развернуть: показан новый день, несохранённый блокнот вчерашнего дня ждёт на шаге назад.
- Конфликт блокнота: набрать текст на телефоне, не сохраняя; изменить блокнот того же дня в вебе; потянуть экран вниз: видны оба текста, «Сохранить» недоступна до выбора.
- VoiceOver читает «Отметка «<пункт>»: <состояние>»; подсказка про якоря исчезает у дня без якорей.

### PHASE-03/226, круг 2: замечания проверки

Тронуто 7 файлов `mod`: `Features/Day/{DayViewModel,DayView}.swift`, `HabitTrackerTests/{DayViewModelTests,DayLogicTests,DayFixtures}.swift`, этот файл (тикет вне git).

- `DayViewModel.swift` — счётчик сохранений блокнота (+1 на старте и на конце). Ответ перечитывания, отправленный до сохранения, во время него или переживший его, не меняет блокнот открытого дня (остальное применяется): поздний GET больше не откатывает сохранённый текст и не поднимает ложный конфликт над дописанным T2. Успешное сохранение снимает конфликт, только если он показывал именно сохранённый текст; иначе чужой текст остаётся с пометкой «заменён вашим сохранением» (`notebookConflictOverwritten`, кнопка «Понятно»). Черновик итога дня хранит базу по каждому полю; сдвиг сервера под набранным даёт `closingConflict`, отправка закрыта до «Оставить мои» / «Взять с сервера». Ответ закрытия обновляет базу итога, так что упавшее тихое перечитывание не делает отправленное неотправленным. `rereadInPlace` обновляет `timeZone`.
- `DayView.swift` — перечитывание по `new == .active && old != .active` (SwiftUI идёт `.background` → `.inactive` → `.active`; условие вынесено в `DayView.shouldReread` и покрыто тестом). Pull-to-refresh зовёт `rereadInPlace()`, а не `load()`: лоадер не подменяет экран, фокус `TextEditor` не теряется. Карточки конфликта блокнота и итога дня.
- Тесты (+8 в `DayViewModelTests`, +1 в `DayLogicTests`): поздний GET до сохранения, дописанный T2 после сохранения и во время него, заменённый чужой текст, конфликт итога (отправка закрыта, оба выбора), черновик итога на устаревшей базе, база после ответа закрытия при упавшем перечитывании; при возврате на день A после шага во время сохранения сервер отдаёт другой текст и конфликта нет (закрепляет ветку стирания черновика). Мутация (отключён пропуск устаревшего блокнота) валит оба теста позднего GET.

Известный предел (не делаем здесь): сохранение блокнота — слепая перезапись. Если клиент не видел чужую правку (перечитывание не случилось), PUT затрёт её. Закрыть можно только серверной проверкой базы (expected base / If-Match) — отдельный тикет.

Проверки: `xcodebuild test` на av04-iPhone17Pro с подписью симулятора — 476 из 476. Не проверено: живой бэкенд, вёрстка карточек конфликта (блокнот, итог дня) глазами, pull-to-refresh и фокус `TextEditor` на устройстве. Для #215 добавлено: тянуть экран вниз во время набора в блокноте — курсор остаётся, текст не пропадает.

## 2026-10-27 — PHASE-03/225: оффлайн-запись через одну очередь (iOS)

Две очереди (`OutboxQueue` записей и `QuickMarkTapQueue` отметок) стали одной `OutboxQueue` с действиями шести видов: запись формы, checklist, быстрая отметка, отметка пункта плана, новый факт, блокнот дня. Таблица путей записи до и после — в тикете #225. Тронуто 20 файлов: 5 `new`, 13 `mod`, 2 удалены.

- `HabitTracker/Cache/OutboxQueue.swift` — mod: `OutboxAction` и его полезные нагрузки (`QueuedTap`, `QueuedDayMark`, `QueuedPlanFact`, `QueuedNotebook`), `OutboxWrite` с ключом, подписью и причиной отказа; SwiftData-модель `PendingWriteRecord` в своём файле `outbox.store` (раньше очередь делила `default.store` с кэшем чтения другой схемы); повтор по порядку, остановка на сети, 401, 408, 429 и 5xx, перевод в «Не отправлено» после 5 ответов 5xx и на любом другом 4xx; замена ждущего «set» того же объекта (кроме отправляемого); `retry` (без проверки, которая отказала, в конец очереди, тот же ключ) и `discard`; `delivered` после доставки.
- `HabitTracker/Cache/OutboxReplay.swift` — new: отправка каждого вида на свой endpoint под ключом; `entry_date` у отметки; сверка отметки плана и блокнота с днём на сервере (GET без `opened=true`).
- `HabitTracker/Cache/OutboxLegacyImport.swift` — new: один раз переносит `quick-mark-taps.json` и `PendingEntryRecord` из `default.store` с их ключами.
- `HabitTracker/Cache/OutboxQueueBar.swift` — new: общая полоса очереди и лист «Ждёт отправки / Не отправлено» с причиной, повтором и удалением.
- `HabitTracker/API/APIClient+Outbox.swift` — new: `fetchDayUnopened`, `liveOutboxSender()`.
- `HabitTracker/API/APIClient+Today.swift` — mod: `TodayScreenAPI.createEntry(_:idempotencyKey:)`. `API/APIClient.swift` — mod: только комментарии к `createEntry`.
- `HabitTracker/Features/Today/TodayViewModel.swift`, `TodayView.swift` — mod: запись формы под ключом с первой попытки, checklist в очередь без сети, строки «pending» строятся из очереди, после доставки день перечитывается; полоса очереди вместо `PendingUploadsBadge`.
- `HabitTracker/Features/QuickMarks/QuickMarksViewModel.swift`, `QuickMarksSection.swift`, `QuickMarksView.swift` — mod: отметка без сети в общую очередь с днём сервера из списка кнопок; отказанная отметка не считается на кнопке; `QueuedTapsBadge` убран, на экране More — общая полоса. `QuickMarkTapQueue.swift` — удалён.
- `HabitTracker/Features/Day/DayViewModel.swift`, `DayView.swift` — mod: день открывается из кэша чтения (тихое перечитывание кэш не берёт); отметка, новый факт и блокнот без сети уходят в очередь и остаются на экране при перечитывании; знак «Записано на телефоне, ждёт отправки» у пункта и блокнота; закрытие дня и правка/удаление факта без сети говорят, что нужен сервер.
- `HabitTrackerTests/OutboxQueueTests.swift` — mod (переписан, 29 тестов): авиарежим → сеть → одна строка на сервере, обрыв посреди отправки, перезапуск с непустой очередью и со списком «Не отправлено», порядок, 5xx/4xx/401, замена и отправка во время полёта, повтор и удаление, смена суток для записи и для отметки, сверка блокнота и отметки, перенос старых очередей. `DayOfflineTests.swift` — new (10). `TodayViewModelTests.swift`, `QuickMarksViewModelTests.swift` — mod (+5, +2, мок отметок перенесён из удалённого `QuickMarkTapQueueTests.swift`).

Известные пределы:

- Отметку задним числом сервер не принимает: у `POST /quick-marks/{id}/events` нет момента нажатия, только сверка `entry_date`. Отметка, сделанная до смены дня и доставленная после, встаёт в «Не отправлено» с кнопкой «Записать в сегодня», а не в свой день. Чтобы она легла в свой день, серверу нужен момент нажатия (`occurred_at`) — отдельный тикет бэкенда.
- День сервера для отметки берётся из списка кнопок (`entry_date`). Если список прочитан до границы дня, а отметка сделана после, без сети, сервер ответит 409 и отметка встанет в «Не отправлено» ложно; «Записать в сегодня» её спасает.
- Срыв «Happened», закрытие дня, правка и удаление факта, отмена отметки, голосовая сводка и чат без сети не работают; причины — в таблице тикета. Категории, журнал, запись из карточки категории и правка записи не подключены в этом срезе.
- Повтор сам срабатывает на смене сети, загрузке экранов и возврате «Дня» из фона; если сеть есть, а сервер лежал и поднялся без смены сети, очередь ждёт следующего такого события.

Для #215 (только на телефоне, авиарежим):
- Авиарежим → запись формы, галочка checklist, быстрая отметка, отметка пункта плана, факт, блокнот → полоса «ждёт отправки: 6» на Today, Quick marks и «Дне» → выключить авиарежим → полоса пропадает, на сервере (веб) по одной записи каждого действия.
- Авиарежим → отметка → выгрузить приложение из памяти → открыть → полоса на месте → сеть → отметка на сервере.
- Отметка в авиарежиме вечером, сеть после границы дня (04:00) → строка в «Не отправлено» с причиной, «Записать в сегодня» пишет в новый день.
- Блокнот в авиарежиме, тот же блокнот правят в вебе, сеть → «Не отправлено», текст телефона виден в листе, «Записать поверх» пишет его.
- «День» открывается в авиарежиме после перезапуска из кэша с плашкой «Offline».
- Первый запуск новой сборки поверх старой с ждущими отметками/записями: они переносятся в общую очередь и уходят.

Проверки: `xcodebuild test` на av04-iPhone17Pro с подписью симулятора — 516 из 516 (до тикета 489), два полных прогона подряд. Мутации: повтор отметки без `entry_date` и блокнот без сверки валят по три теста. Не проверено: вёрстка полосы, листа очереди и знака «ждёт отправки» глазами; живой бэкенд; телефон.

### PHASE-03/225, круг 2: замечания проверки

Перед правками влит `main` (#226, #227, #131, #221), конфликт только в этом файле. Тронуто 14 файлов, все `mod`: `Cache/{OutboxQueue,OutboxReplay,OutboxLegacyImport,OutboxQueueBar}.swift`, `Features/QuickMarks/QuickMarksViewModel.swift`, `Features/Today/TodayViewModel.swift`, `Features/Day/{DayViewModel,DayView}.swift`, `HabitTrackerTests/{OutboxQueueTests,QuickMarksViewModelTests,TodayViewModelTests,DayOfflineTests}.swift`, этот файл и тикет (тикет вне git).

- **День отметки.** Оффлайн-отметка закрепляется за днём списка кнопок, только если он совпадает с местным днём нажатия. Иначе (кэш за вчера, список из 23:50) уходит без `entry_date`, в сегодня сервера, как прямое нажатие.
- **Сверка, которую не прочитать.** Нечитаемый ответ проверочного GET (`invalidResponse`) у отметки плана и блокнота больше не считается доставкой. Запись встаёт в «Не отправлено» с причиной «не удалось сверить». Доставкой считается только нечитаемый 2xx самого запроса записи.
- **Счётчик 5xx.** `attempts` заменён на `serverErrors` — 5xx подряд. Ожидание сети и 401 сбрасывают счётчик, так что обрывы связи больше не приближают перевод в «Не отправлено».
- **Вид причины.** Причина хранится вместе с видом: `OutboxFailureKind` пишется на диск. Кнопка повтора выбирается по виду, а не по сравнению строк. 409 отметки без дня называется «кнопка выключена», а не «день сменился».
- **Повтор из списка** (`retry`) сразу запускает отправку.
- **Запись поверх ждущей.** Checklist на Today, отметка пункта и блокнот на «Дне» идут через очередь, если там ещё ждёт запись того же объекта. Новая заменяет старую и уходит сразу; старая не может лечь последней.
- **Доставка в фоне.** Today перечитывает записи дня тихо, без лоадера и второго `load()`. Мёртвый `pendingUploadCount` убран.
- **Перенос старых очередей.** Импорт запускается, только если открылось хранилище на диске. Источник старых записей теперь шов `oldEntries`. Добавлен тест «второй запуск ничего не делает».
- **Кэш «Дня» после полуночи.** Если в кэше не сегодняшний день, «День» пишет «Сегодняшнего дня в кэше нет: показан …».
- **401.** Полоса очереди говорит «сервер не принял ключ API — проверьте Settings», пока запись не пройдёт.
- **Мелочи.** Нечитаемый id поля checklist больше не превращается в поле 0. Кнопки отметок перерисовываются на любое изменение очереди (удаление из списка снимает «+1»). Ключ факта без `?? ""`. `enqueue` и `restore` идут через одну функцию.
- **Тесты.** `OutboxQueueTests` +10, `QuickMarksViewModelTests` +2, `TodayViewModelTests` +1 (и проверка «без лоадера»), `DayOfflineTests` +3. Мутации (откат каждого из трёх блокеров и обхода очереди checklist) валят свои тесты.

Проверки круга: `xcodebuild test` на av04-iPhone17Pro с подписью симулятора после слияния main — 558 из 558, предупреждений в тронутых файлах нет.

Не сделано (известный предел): экраны по-прежнему ждут `flush` перед чтением (Today, Quick marks, «День»). Параллельное чтение гоняет непотокобезопасные двойники API в тестах — тот же класс гонки, что в круге 1. Нужны потокобезопасные двойники, это отдельная работа. VoiceOver «ждёт отправки» на кнопках отметок не добавлен. Быстрая отметка после смены суток ляжет в свой день только после #236 (`occurred_at`).

Для #215 добавлено: поставить сборку круга 2 поверх сборки до #225, у которой есть ждущие отметки (`quick-mark-taps.json`) и записи (`PendingEntryRecord` в настоящем `default.store`). После запуска они видны в полосе и уходят на сервер по одной. Перенос с настоящего `default.store` на симуляторе не проверялся: тест идёт на хранилище в памяти. Утром в авиарежиме нажать кнопку при списке за вчера: отметка ждёт и потом уходит, а не встаёт в «Не отправлено».

## 2026-10-27 — PHASE-03/131: HealthKit-насос (шаги и пульс покоя за 7 дней → `POST /health/samples`)

Клиент остаётся насосом: читает сырые семплы и отправляет шесть полей `HealthSampleIn`, сервер считает всё сам. Отправка идемпотентна без `Idempotency-Key`: сервер перезаписывает часовые корзины по естественному ключу. Очереди на диске нет намеренно: значения здоровья не покидают память, повтор = новое чтение окна из HealthKit. Ревизия Alembic не нужна, таблицы есть с `PHASE-02/64`. Тронуто 7 файлов `new`, 3 `mod`.

- `HabitTracker/API/DTOs+Health.swift` — new: `HealthSampleDTO` ровно из шести полей, чанк, ответ сервера.
- `HabitTracker/API/APIClient+Health.swift` — new: `HealthSamplesAPI.postHealthSamples`.
- `HabitTracker/Features/HealthSync/HealthKitSampleSource.swift` — new: шов `HealthStoreQuerying` над `HKHealthStore` (только чтение, share-множества в сигнатурах нет; окно со `strictStartDate`), `HealthSampleMapper` — единица из каталога, UTC с миллисекундами, смещение устройства на момент семпла, `HKMetadataKeyTimeZone` семпла важнее.
- `HabitTracker/Features/HealthSync/HealthPump.swift` — new: окно «сегодня и шесть дней до», целые метрики в чанке до 50 000 (метрика больше чанка — отказ без частичной отправки), до 3 попыток только на сети и 5xx, 401/422 без повтора, параллельные вызовы сливаются в один прогон, запуск при старте не показывает лист разрешений. В лог идёт только класс ошибки.
- `HabitTracker/Features/HealthSync/HealthSyncView.swift` — mod: секция «Отправка на сервер» с кнопкой и итогом словами (`samples_received`, `buckets_written` от сервера); пустая неделя отправляет в Настройки.
- `HabitTracker/App/HabitTrackerApp.swift` — mod: строка `.task { HealthPump.shared.syncIfAuthorized() }` перед `.appLock()`, то есть прогон после разблокировки.
- `HabitTrackerTests/{HealthPumpTests,HealthSampleMappingTests,HealthAPIClientTests}.swift` — new: 14 + 7 + 2 теста на подделке `HKHealthStore` и `MockURLProtocol`; `HealthSyncViewModelTests.swift` — mod: +3 теста кнопки.
- `services/backend/tests/test_health_device_chunk.py` — new: приём тела ровно в кодировке iOS (миллисекунды, `count\/min`, прогулка через границу часа), дневная свёртка и повторная отправка.

Проверки: `xcodebuild test` на av08-iPhone17Pro с подписью симулятора — 473 из 473; `pytest tests/` — 1928 passed; `alembic heads` — одна строка. Мутация «без слияния вызовов» роняет `testConcurrentCallersShareOneRun`.

Не проверено (устройство, для #215): лист разрешений при первом входе и отказ в нём; реальные семплы и единицы из «Здоровья»; дневная сумма шагов против приложения «Здоровье» на трёх днях; `/health` на маке после кнопки; прогон при старте после Face ID; подпись Personal Team с HealthKit.

## 2026-10-27 — PHASE-03/229: экран «Неделя» (weekly review и weekly stats, iOS)

Нативный экран на ответе #221: `GET /week-review[/{iso}]` одним запросом, текст итога — `POST /week-review/{iso}/narrative` по кнопке. Строка «Неделя» в More. Запись не нужна: экран читает, итог от ИИ требует сети.

- Данные: окно недели, цифры против прошлой (дельты считает сервер, клиент не вычитает), семь дней с лучшим и худшим словами, время по ролям и категориям, серии «избегать», здоровье; сон с `available: false` — «Метрика не подключена». `null` показывается как «—» или «Нет данных», не нулём.
- Неполная неделя помечена плашкой с обоими счётчиками (учтено N из 7, сравнение с первыми M днями прошлой). Пустая неделя говорит об этом и не предлагает итог — тест пустоты повторяет серверный, кнопка выключена там же, где сервер ответил бы 422.
- Оффлайн: чтение через `ReadThroughCache`, каждая неделя под своим ключом `week.review.<iso>`, текущая ещё и под своим кодом, чтобы шаг назад-вперёд работал без сети. Показан последний ответ с пометкой «Нет связи · обновлено 27 окт., 09:41».
- Навигация по неделям: коды соседей берутся из ответа сервера. Запоздавший ответ уже покинутой недели отбрасывается (счётчик чтения). Pull-to-refresh идёт на месте без смены экрана, ошибка обновления пишется строкой, данные остаются.
- Итог: 503 / 502 / 422 / нет сети — каждый своими словами; таймаут клиента для итога 120 с, как у Insights. Текст не хранится; при смене недели во время записи результат не показывается на чужой неделе.
- Экран не заводит свой `NavigationStack`; общие файлы тронуты добавлением: `AppNavigation.swift` (case `week`, заголовок, значок), `RootView.swift` (одна ветка `WeekView()`).

Файлов тронуто: 15 (13 new, 2 mod).

- `HabitTracker/API/DTOs+Week.swift`, `API/APIClient+Week.swift` — new: типы ответа (Codable, для кэша) и `WeekAPI`.
- `HabitTracker/Features/Week/{WeekFormat,WeekViewModel,WeekSections,WeekView}.swift` — new: словарь, состояние, блоки, экран.
- `HabitTracker/App/{AppNavigation,RootView}.swift` — mod: строка в More.
- `HabitTrackerTests/{WeekFixtures,WeekAPIClientTests,WeekFormatTests,WeekViewModelTests}.swift` — new: 9 + 21 + 21 тест.

Проверки: `xcodebuild test` на av06-iPhone17Pro с подписью симулятора — 566 из 566. Ключи фикстуры сверены с `WeekReviewResponse.model_json_schema()` сервера рекурсивно — расхождений 0.

Не проверено (для #215): вёрстка на телефоне и SE (семь ячеек дней в строке, длинные названия категорий, динамический шрифт, VoiceOver); живой ответ сервера — бэкенд на 8879 не поднимался (схема в базе роя не накатывалась), контракт сверён только по схеме; оффлайн в авиарежиме на устройстве; итог от настоящей модели; pull-to-refresh и переходы между неделями руками.

## 2026-10-27 — PHASE-03/231: остаток экрана «День» после #226 (iOS)

Файлы (0 new, 5 mod): `Features/Day/{DayViewModel,DayView}.swift`, `HabitTrackerTests/{DayViewModelTests,DayFixtures}.swift`, этот файл.

- `DayViewModel.swift` — шаг A→B→A во время сохранения: текст последнего сохранения помнится по дате вместе с эпохой старта (`savedNotebooks`); ответ за эту дату, отправленный не позже старта сохранения, берёт его вместо серверного, даже когда на экране другой день (раньше такой ответ откатывал блокнот к тексту до сохранения). Карточка «ваше сохранение заменило текст с сервера» живёт до «Понятно», а не до первого перечитывания (сбрасывается со сменой дня; новый конфликт её вытесняет). `adoptSentClosing` снимает `closingConflict`: ответ закрытия — свежее основание обоих полей. `rereadInPlace(reportingFailure:)` — pull-to-refresh при ошибке сети ставит `actionError` «День не обновился: …» (отменённая задача молчит); фон, полночь, смена пояса тихие. `timeZone` присваивается только при отличии. Сборка «<что не получилось>: <причина>» вынесена в `failure(_:_:)`, её берёт и сохранение блокнота.
- `DayView.swift` — `refreshable` зовёт `rereadInPlace(reportingFailure: true)`.
- Тесты (+9 в `DayViewModelTests`, хук `duringClosing` в `MockDayAPI`): A→B→A с ответом, ждущим конца сохранения; ответ после сохранения снова берёт серверный текст; перечитывание во время сохранения отвечает уже записанным «T» поверх набранного «T2» (проверка внутри хука: конец сохранения сам гасит конфликт над «T»; мутация без `isSavingNotebook ||` краснит тест); карточка пережила перечитывание и ушла со сменой дня; конфликт итога, поднятый за время закрытия, снят ответом; ошибка и успех pull-to-refresh; тихое перечитывание без `actionError`; тот же пояс не публикуется заново. В `testALateReadThatPredatesTheSaveDoesNotRollTheNotebookBack` проверка `"done"` заменена ответом с отметкой `failed`.

Не проверено: живое устройство, вёрстка. Для #215 (только на телефоне): авиарежим, потянуть экран «День» вниз: алерт «День не обновился: …», экран и набранный блокнот на месте; фон и возврат в авиарежиме — без алерта; карточка «Это был текст с сервера, ваше сохранение его заменило» остаётся после pull-to-refresh до «Понятно».
## 2026-10-27 — PHASE-03/230: остаток голосовой сводки после #227 (iOS)

Общие типы плана с чатом, перечитывание Today после любого закрытия листа, защита экрана «Рассказать день» в «Ещё» от сброса стека повторным нажатием вкладки, мелочи.

- Типы плана: серверная схема одна (`LogMetricOp`, `CheckOp`, `JournalOp`), в приложении теперь тоже один набор. `op` и `existingEntryId` — поля общего типа (в плане чата последнего нет), `mode` — enum; чат `replace` не шлёт, сервер его не принимает. Флаги, которых нет в ответе, читаются как `false` (как раньше в чате). Чат теперь отправляет `op` в теле apply: схема сервера его допускает.
- Today: `VoiceDayButton(onDismiss:)` вешает перечитывание на `.sheet(isPresented:onDismiss:)`. Закрытие после записи, после 409 и по «Закрыть» ведёт к одному перечитыванию (раньше 409 и «Закрыть» не перечитывали).
- Вкладка «Ещё»: `AppNavigation.setMorePath` отказывает во всплытии стека, пока экран поднял `moreLeaveBlocked` (модификатор `holdsMoreScreen`); отказ меняет `refusedPops`, чтобы стек перерисовался от пути. `DailySummaryRetainer` отдаёт следующему входу модель с неподтверждённой записью, иначе всплытие системой всё равно убило бы ключ. Решено по коду: срабатывание и сброс стека системой на устройстве не проверены.
- Мелочи: `.topBarLeading`; `EngineAudioInput.start()` без `installTap` бросает `.unavailable` (экран показывает «Не удалось включить микрофон»); `FakeSpeech.holdsFinalPhrase` держит последнюю фразу до сигнала теста, тест отмены стал детерминированным (50 прогонов подряд зелёные).

Файлов тронуто: 17 (3 new, 14 mod).

- `HabitTracker/API/DTOs+PlanOperations.swift`, `App/MoreLeaveGuard.swift`, `HabitTrackerTests/PlanOperationDTOTests.swift` — new.
- `HabitTracker/API/{DTOs+Chat,DTOs+DailySummary}.swift`, `App/{AppNavigation,RootView}.swift`, `Features/Chat/{ChatViewModel,ChatPlanCardView}.swift`, `Features/DailySummary/{DailySummaryView,DailySummaryViewModel,SpeechDictation}.swift` — mod.
- `HabitTrackerTests/{AppNavigationTests,ChatAPIClientTests,ChatViewModelTests,DailySummaryViewModelTests,SystemSpeechRecognizerTests}.swift` — mod (в тестах чата только имена типов и `.append` вместо `"append"`).

Проверки: `xcodebuild test` на av08-iPhone17Pro с подписью симулятора — 621 из 621 (было 609, +12 новых).

Не проверено (для #215): сам сброс стека повторным нажатием «Ещё» и работа защиты (мигание, зацикливание, сохранение текста); перечитывание Today после закрытия листа на устройстве (поведение `onDismiss` не покрыто автотестом, это вид).
## 2026-10-27 — PHASE-03/234 (+часть 233): шаги часовыми суммами HealthKit, «%» как `fraction`

Накопительные метрики каталога насос теперь берёт `HKStatisticsCollectionQuery` (`.cumulativeSum`, час, якорь — местная полночь начала окна): HealthKit сам дедуплицирует iPhone и часы по приоритету источников, как «Здоровье». Каждая часовая сумма уходит одной записью `HealthSampleIn` (начало и конец часа, сумма, единица, смещение пояса телефона на начало часа); пустой час не отправляется. Дискретные (пульс покоя) — `HKSampleQuery`, как раньше. Поправка записана в ADR-0020 A2. Тронуто 10 файлов, все `mod`.

- `HabitTracker/Features/HealthSync/HealthMetricCatalog.swift` — mod: у метрики вид (`cumulative`/`discrete`, сверен тестом с `aggregationStyle` HealthKit) и две единицы: `unit` — в чём читать из HealthKit, `wireUnit` — что сказать серверу. Сатурация и процент жира: `%` → `fraction` (`HKUnit.percent()` отдаёт 0.97).
- `HabitTracker/Features/HealthSync/HealthKitSampleSource.swift` — mod: единственный шов над `HKHealthStore` — добавлены `hourlySums` (часы HealthKit как `HealthHourSum`) и `latestSample`; маппер переводит и семпл, и часовую сумму; комментарий о `strictStartDate` переписан под дискретные метрики.
- `HabitTracker/Features/HealthSync/HealthPump.swift` — mod: ветка по виду метрики; чтение окна и перевод в DTO — `nonisolated static`, вне главного потока; новые классы отказа `authorizationFailed` (раньше выдавался за «нет данных Здоровья») и `encodingFailed` (раньше считался сетью и повторялся трижды).
- `HabitTracker/Features/HealthSync/HealthDataReader.swift` — mod: читает через тот же `HealthStoreQuerying`, второго шва над `HKHealthStore` нет.
- `HabitTracker/Features/HealthSync/HealthSyncView.swift` — mod: тексты для `.skipped` (кнопка попала в прогон при старте), `authorizationFailed`, `encodingFailed`.
- `HabitTrackerTests/{HealthPumpTests,HealthSampleMappingTests,HealthSyncViewModelTests}.swift` — mod: двойник `HKStatisticsCollectionQuery` в `FakeHealthStore`; «iPhone + часы» дают одну сумму и сырые семплы шагов не читаются; час до и после полуночи; повтор часа 02 при переходе на зимнее время (смещения 120 и 60); пустые часы; `HKQuantity(.percent(), 0.97)` → `fraction` 0.97; `EncodingError` без повтора; отказ в запросе разрешения; читатель экрана на общем шве.
- `services/backend/tests/test_health_device_chunk.py` — mod: тело устройства теперь с часовыми суммами шагов; суммы по обе стороны полуночи ложатся целиком в свои дни; повтор часа 02 складывается в одну корзину; `fraction` 0.97 сатурации даёт 97.

`window_start` (#233) для накопительных метрик не нужен: первый час окна начинается ровно в полночь, семпл через неё HealthKit делит сам. Для дискретных тоже не нужен: сервер кладёт показание в час его начала, а `strictStartDate` берёт ровно показания с началом внутри окна, поэтому час 00 старшего дня получает все свои показания. Заметка на будущее: если появится дискретная метрика с интервальными семплами, которые сервер начнёт делить по часам, границу придётся пересмотреть.

Известный предел: у часовой суммы нет пояса семпла, часы ложатся по поясу телефона на момент чтения. После перелёта корзины прошлых дней окна пишутся под новыми местными ключами, а старые ключи без данных в новом поясе не перезаписываются — так было и до #234 для семплов без `HKMetadataKeyTimeZone`.

Проверки: `xcodebuild test` на av04-iPhone17Pro с подписью симулятора — 625 из 625, предупреждений по файлам HealthSync нет; `pytest tests/` — 2052 passed, 2 skipped (23 мин под нагрузкой соседей); `ruff check`, `ruff format --check` — чисто; `alembic heads` — одна строка. Вынос чтения окна с главного потока закреплён структурой (`nonisolated static`), отдельного теста на поток нет.

Не проверено (устройство, для #215): дневные шаги на `/health` против «Здоровья» на трёх днях, в том числе в день с часами на руке; настоящий `HKStatisticsCollectionQuery` (якорь, прорейтинг семпла через полночь, неполный текущий час); сатурация и процент жира с часов или весов — `pumpedMetrics` их пока не включает; текст кнопки при попадании в прогон при старте.

## 2026-10-27 — PHASE-03/236 и PHASE-03/242: момент нажатия в очереди и остаток оффлайн-очереди

Оффлайн-нажатие быстрой отметки несёт момент нажатия (`QueuedTap.occurredAt`) и уходит с `occurred_at` без `entry_date`. День считает сервер по своей границе (04:00), поэтому закреплять нажатие за днём списка больше не нужно: `localDayOfPress` удалён. Прямое нажатие `occurred_at` не шлёт. Отказ 422 на момент (старше семи дней, часы спешат) встаёт в «Не отправлено» с кнопкой «Записать в сегодня», повтор оттуда уходит без момента. Записи очереди, сделанные до сборки, читаются (новое поле необязательное) и ведут себя по-старому. Тронуто 13 файлов кода, все `mod`.

- `Cache/OutboxQueue.swift` — момент у `QueuedTap`; `replacedStates`/`replacedContents` у отметки плана и блокнота — замена ждущей записи принимает и состояния заменённых; 422 с моментом → `.dayTurned` с причиной `pressTimeRefusedReason`; `retryWarning(for:)`.
- `Cache/OutboxReplay.swift` — `occurred_at` в ISO 8601 UTC; сверка отметки и блокнота пропускает состояние любой заменённой записи.
- `Cache/OutboxQueueBar.swift` — над кнопками «Не отправлено» предупреждение «Повтор запишет это поверх более новой записи …»; у нажатия — «Нажато …».
- `API/DTOs+Today.swift` — `QuickMarkEventRequestDTO.occurredAt` (необязательное, nil не уходит в тело).
- `Features/QuickMarks/QuickMarksViewModel.swift`, `QuickMarksSection.swift` — момент нажатия в очередь; `waitingCaption(of:)` и `accessibilityValue` «ждёт отправки: N» на обеих целях карточки; справочник читается вместе с отправкой очереди.
- `Features/Day/DayViewModel.swift` — плашка «Показан день из кэша: …» вместо «Сегодняшнего дня в кэше нет» (с 00:00 до 04:00 кэш держит как раз день сервера); чтение вместе с отправкой очереди.
- `Features/Today/TodayViewModel.swift` — чтение вместе с отправкой; перечитывание после фоновой доставки не пишет ошибку в `saveErrorMessage`.
- Тесты: `OutboxQueueTests` +8 (момент без дня, 422 и «Записать в сегодня», старая запись без момента читается, замена после потерянного ответа у отметки и блокнота, чужое состояние всё ещё конфликт, предупреждение у повтора, добавления без предупреждения), `QuickMarksViewModelTests` +3 и 2 переписаны (01:00 → доставка 08:00 несёт 01:00, VoiceOver, чтение раньше ответа медленной отправки), `DayOfflineTests` +1 и текст плашки, `TodayViewModelTests` +1. Двойники `MockQuickMarksAPI`, `MockDayAPI` (`DayFixtures.swift`), `MockTodayAPI`, `FakeOutboxServer` — `@MainActor`: экран читает их, пока очередь отправляет через них же.

Миграция хранилища очереди со схемы круга 1 (`attempts`) не нужна для `main`: круг 1 в `main` не сливался, `main` перешёл с `PendingEntryRecord` (переносит `OutboxLegacyImport`) сразу на схему круга 2 (`49a5f13`).

Проверки: `xcodebuild test` на av09-iPhone17Pro с подписью симулятора — 621 из 621, предупреждений в тронутых файлах нет.

Для #215 (на телефоне): в авиарежиме нажать кнопку в 01:00, сеть утром — отметка в списке за вчерашний день сервера, а не за сегодня; в листе очереди строка «Нажато …»; VoiceOver на кнопке с ждущим нажатием говорит «ждёт отправки: 1»; «День» в авиарежиме после полуночи пишет «Показан день из кэша: …». Если на телефоне стояла сборка круга 1 #225 с ветки — открыть новую сборку и убедиться, что ждущие записи на месте. Не проверено: телефон, вёрстка предупреждения и строки «Нажато» глазами.

### PHASE-03/236 и PHASE-03/242, круг 2: замечания независимой проверки

Тронуто 10 файлов, все `mod`: `Cache/{OutboxQueue,OutboxReplay}.swift`, `Features/{Today/TodayViewModel,QuickMarks/QuickMarksViewModel,Day/DayViewModel}.swift`, тесты `OutboxQueueTests`, `QuickMarksViewModelTests`, `TodayViewModelTests`, `DayOfflineTests`, этот файл.

- **Старый ответ чтения не затирает новый.** `load()` читает вместе с отправкой очереди. Поэтому ответ чтения, ушедшего до доставки, может вернуться после перечитывания, которое запустила доставка. Today (записи дня) и Quick marks (справочник) нумеруют чтения: показывается ответ только новее показанного. Если перечитывание упало, остаётся ответ загрузки, а не пустой экран. «День» перечитывает на любую доставленную запись дня, пока идёт загрузка (`shownDate == nil`, шаг на другой день), и старый ответ отбрасывает `loadGeneration`. Если такое перечитывание упало, экран уходит в ошибку, а не крутит загрузку. Тесты «чтение до доставки отвечает после перечитывания» на всех трёх экранах.
- **Состояние заменённой записи принимается, только если она уходила в сеть.** `OutboxWrite.mayHaveLanded` (хранится на диске, `PendingWriteRecord.mayHaveLanded`, по умолчанию false) ставится на таймаут и обрыв после отправки. Нет связи, нет хоста, ошибка DNS его не ставят. Иначе отметку «done», сделанную в вебе, молча перезаписывала замена ждущей отметки телефона.
- **Причина 422** теперь называет и третью возможность: сервер ещё не обновлён и `occurred_at` не знает. Порядок выкладки: бэкенд раньше iOS, иначе каждый повтор нажатия из очереди получит 422 и встанет в «Не отправлено» (спасает «Записать в сегодня»).
- **Мелочи.** `occurred_at` уходит с миллисекундами через один общий форматтер. Плашка «Дня» в тесте сверяется целиком. Тест тихого перечитывания Today ждёт ответа чтения по счётчику двойника, без `sleep`.
- Не сделано: причину «время нажатия» нельзя показывать только при 422 по `occurred_at`. `APIClientError.unexpectedStatus` не несёт тела ответа. Сейчас она показывается на любой 422 нажатия, у которого есть момент.

Мутации: откат каждого из четырёх исправлений (поколения Today и Quick marks, перечитывание «Дня» во время загрузки, флаг `mayHaveLanded`) валит свои тесты, всего 6 падений.

### PHASE-03/236 и PHASE-03/242, круг 3

Тронуто 11 файлов: `Cache/OutboxQueue.swift`, `Features/{Day/DayViewModel,Today/TodayViewModel,QuickMarks/QuickMarksViewModel}.swift`, тесты `OutboxQueueTests`, `DayOfflineTests`, `TodayViewModelTests`, `QuickMarksViewModelTests` (`mod`), `TestWaiting.swift` (`new`), этот файл.

- **Блокер: прямая запись, потерявшая ответ.** У `enqueue` появился параметр `mayHaveLanded`. «День» передаёт `OutboxQueue.mayHaveLanded(after: error)` прямой попытки для отметки плана и блокнота, функция теперь `internal`. Today и Quick marks этот флаг не нужен: их записи в очереди — добавления (запись, нажатие), а у checklist замена ничего не сверяет. Тесты: отметка и блокнот с таймаутом прямого PUT, сервер уже держит их состояние, следующая запись уходит без конфликта.
- **502 и 504** считаются ответом, который мог дойти, и при прямой попытке, и в очереди (`settle` для 5xx). Тест кодов проверяет обе группы целиком: не уходило — нет связи, нет хоста, DNS, 500, 503, 409, 401, конфликт сверки; могло дойти — таймаут, обрыв (`networkConnectionLost`), TLS, 502, 504.
- **«День»: упавшее перечитывание во время загрузки.** Выбран счётчик чтений, как на Today и Quick marks, а не откат на `cache.load`. `loadGeneration` теперь растёт только от загрузки (смена дня отбрасывает ответы, отправленные раньше), а перечитывание берёт номер чтения. Показывается только ответ новее показанного. Упавшее перечитывание экран не трогает: ответ самой загрузки остаётся. Ошибку «Дня» ставит только сама загрузка, если ничего новее не показано.
- **Кэш.** Отброшенный ответ загрузки уже лёг в кэш внутри `cache.load`. Сразу после отбрасывания в кэш возвращается то, что на экране: день в «Дне», справочник в Quick marks, записи в снимке Today. Перечитывание Today и Quick marks тоже пишет в кэш. Без этого кэш держал бы более старое, чем экран. Метку «без сети» Today не ставит, если ответ загрузки из кэша, а перечитывание уже показало свежие записи.
- **Совместимость хранилища.** Тест открывает файл, записанный моделью круга 2 (`PendingWriteRecord` без `mayHaveLanded`, копия модели в тесте), новой схемой. Запись читается, флаг false. Лёгкая миграция SwiftData справляется без `VersionedSchema`.
- **Ниты.** `waitUntil` вынесен в `TestWaiting.swift` и падает через `XCTFail` по таймауту. Новые тесты вписаны в строки summary.

Мутации: откат флага прямой попытки, 502/504, повторной записи кэша в трёх моделях валит 7 тестов. Возврат «Дня» к поведению круга 2 (перечитывание сбрасывает поколение, сбой ставит ошибку) валит тест упавшего перечитывания.


## 2026-10-27 — PHASE-03/248 и PHASE-03/256: экран «День» без ложных конфликтов, остатки очереди

Тронуто 8 файлов iOS (все `mod`; `TodayViewModel` ещё и по просьбе координатора): `Features/Day/DayViewModel.swift`, `Cache/OutboxQueue.swift`, `Features/Today/TodayViewModel.swift`, тесты `DayViewModelTests`, `DayOfflineTests`, `DayFixtures`, `OutboxQueueTests`, `TodayViewModelTests`.

- **A→B→A.** Сохранение закончилось на другом дне, а черновик набран поверх той же базы: черновик перебазируется на сохранённый текст (`Typed(draft.text, base: text)`). Возврат на A не поднимает «изменился на сервере» с собственным текстом.
- **Третий текст в устаревшем ответе.** `savedNotebooks` хранит `(text, base, epoch)`. Ответ подменяется на сохранённый текст, только если он равен базе или тексту сохранения. Иначе на экране остаётся сохранённый текст, `notebookConflict` держит третий, сохранение ждёт выбора.
- **Кэш прежнего дня.** Загрузка пишет в кэш сама при ответе. `newestCached[key]` помнит ответ самого нового чтения по ключу; запоздавшая загрузка возвращает его до проверки поколения. Тихое перечитывание кэш не восстанавливает: оно туда не писало.
- **502/504 при прямой отметке.** В круге 1 было тихое перечитывание; круг 2 его снял: отметка ставится в очередь с `mayHaveLanded: true` (см. круг 2). Ответ 500 откатывается без очереди.
- **Today: второй `load()`.** `.loading` ставится только пока данных нет; повторная загрузка (pull-to-refresh, закрытый лист голосовой сводки) держит `.loaded` и прокрутку, сбой идёт в `saveErrorMessage` («Экран не обновился: …»). Первый сбой остаётся `.failure`.
- **Мелочи.** Карточка «сохранение заменило текст» не возвращается поверх того же серверного текста; `savedNotebooks` не пишется при офлайн-постановке; `.secureConnectionFailed` в «не дошло» (тело при сбое TLS не уходит); метка кэша Today после перечитывания записей остаётся возрастом категорий и стриков; хуки `MockDayAPI` бросают ошибки вместо `try!`, а `tearDown` обоих тестовых классов падает, если выставленный хук не сработал (`hooksNeverRun`).

Проверки: `xcodebuild test` на av04-iPhone17Pro с подписью симулятора — 682 из 682. Мутации: старый код при новых тестах валит 13 проверок в 8 тестах; снятие `guard generation == loadGeneration` валит `testARereadAnsweredWhileAnotherDayLoadsIsNotShown`, снятие `!Task.isCancelled` — `testACancelledPullToRefreshSaysNothing`; возврат безусловного `.loading` в Today — два теста второй загрузки. Не проверено: экран глазами, телефон; отдельного теста на «`savedNotebooks` не пишется при офлайн-постановке» нет (в наблюдаемом поведении очередь перекрывает этот текст сама).

### PHASE-03/248 и PHASE-03/256, круг 2

Тронуто: `Features/Day/DayViewModel.swift`, `Features/Today/TodayViewModel.swift`, тесты `DayViewModelTests`, `DayOfflineTests`, `TodayViewModelTests`; бэкенд — `tests/test_quick_mark_occurred_at.py`.

- **Блокер: строка «Экран не обновился» на Today.** `TodayViewModel` помнит строку, которую написал сбойный `load()`, и удачный `load()` снимает именно её. Ошибка другого действия (сохранение) остаётся.
- **Очередь и `savedNotebooks`.** В ветке «старая запись ждёт в очереди» запись `savedNotebooks` ставится, только если после `flush` записи этого блокнота нет в очереди совсем: ни ожидающей, ни отказанной (раньше считалась дошедшей). Тесты на обе ветки: ответ чтения со старой базой не превращается в текст, который сервер не принял.
- **Третий текст.** Черновик строится поверх старой базы (`Typed(T, base: O)`), поэтому следующее тихое перечитывание с тем же W снова поднимает конфликт; карточка исчезает только по выбору («оставить мой», «взять серверный»). Кнопка сохранения при этом включена, но заблокирована конфликтом.
- **Прямая отметка с 502/504.** Выбран второй вариант тикета: отметка ставится в очередь с `mayHaveLanded: true`, как после таймаута, а не откатывается. Перечитывание после отказа убрано: оно могло проиграть бэкенду, дописавшему запись позже. Ответ 500 откатывается без очереди. Следствие: при долгом сбое прокси отметка остаётся на экране с признаком очереди и после серии ошибок уходит в список «не отправлено».
- **Нити.** Восстановленная копия кэша «Дня» берёт метку времени чтения, из которого она пришла; `newestCached` держит не больше 8 дней (вытесняется самое старое чтение); `tearDown` обоих классов зовёт `super`.
- **Бэкенд.** Тест ветки `other-button`: исходный итог дня равен 250 (не None), после проигранной вставки он тот же, журнал дня содержит одно событие, 409 называет другую кнопку.

Проверки: `xcodebuild test` на av04-iPhone17Pro с подписью симулятора — 760 из 760 после слияния main 055fa7f (#254); до слияния main было 719. Бэкенд: 7 файлов quick_marks — 106 passed, `ruff`, `mypy --strict` чисто. Мутации: снять снятие строки, убрать проверку очереди, вернуть базу = текст, `cache.now()` вместо метки чтения, не ставить 502/504 в очередь — каждая валит свой тест.

### PHASE-03/243 и PHASE-03/250: остаток «Недели» и голосовой сводки

Тронуто 20 файлов. `new`: `services/backend/tests/test_ios_week_fixture.py`. Остальные `mod`: `Features/Week/{WeekFormat,WeekSections,WeekView,WeekViewModel}.swift`, `Features/DailySummary/{DailySummaryView,DailySummaryViewModel}.swift`, `Features/Chat/ChatPlanCardView.swift` (один `switch`), `API/DTOs+PlanOperations.swift`, `App/{AppNavigation,MoreLeaveGuard,RootView}.swift`, тесты `Week{Fixtures,FormatTests,ViewModelTests}`, `DailySummaryViewModelTests`, `PlanOperationDTOTests`, `AppNavigationTests`, `README.md`, этот файл.

- **#243.** Тайм-аут итога называется «Модель отвечает долго», клиентский тайм-аут 150 с при серверных 120 (`LLM_TIMEOUT_SECONDS`): 502 сервера приходит раньше. Кнопки переходов имеют зону 44 pt на каждой кнопке. Свежий ответ недели, открытой по коду, кладётся и под `current`. Плашка «не закончилась» скрыта у кэшированной недели, чей `endsOn` позади (сутки по часовому поясу недели и `dayStartHour`). «Текущая» не показывается на текущей неделе. Итог пишется одним запросом на неделю: счётчик `narrativeToken` по образцу `generation`, возврат на неделю, где итог ещё пишется, показывает «пишу». `.task` при возврате читает на месте (`appear()`). `DayOutcome` вместо сравнения русского слова.
- **Сверка фикстуры** — `tests/test_ios_week_fixture.py`: достаёт JSON из `WeekFixtures.swift` и сверяет с `WeekReviewResponse` (те же поля на каждом уровне, ответ проходит схему). Переименование поля на сервере краснит тест. Без исходников iOS рядом (образ docker) тест пропускается.
- **Решение про цифры здоровья** — раздел в `ios/HabitTracker/README.md`.
- **#250.** Лист голоса возвращает управление Today, только если из него уходила запись (`mayHaveChangedTheDay`, не сбрасывается `reset()`); закрытие без записи не вызывает ни `load`, ни `flush`. После настоящей записи Today по-прежнему зовёт `reload()` со своим загрузчиком: `TodayViewModel.load` принадлежит #248. `JournalOpDTO` читает ответ без `op`. Защита выхода из «Ещё» — набор держателей `moreLeaveHolders` с токеном на экземпляр вместо общего `Bool`. Мелочи: `.accessibilityAction(.escape)`, два `init` у `DailySummaryView` (`onApplied` больше не теряется молча), retainer усыновляет модель в `onAppear` и отпускает в `onDisappear` после обычного выхода, `switch` по `JournalOpDTO.Mode` в карточке чата, заголовок `PlanOperationDTOTests`.
- Не проверено на устройстве: повторное нажатие вкладки «Ещё», мигание, «tried to update multiple times per frame», рассинхрон пути — это #215.

### PHASE-03/243 и PHASE-03/250, круг 2

Тронуто 11 файлов, все `mod`: `Features/Week/{WeekFormat,WeekViewModel}.swift`, `Features/DailySummary/DailySummaryView.swift`, `API/DTOs+PlanOperations.swift`, `App/RootView.swift` (шапка), тесты `WeekFixtures`, `WeekFormatTests`, `WeekViewModelTests`, `DailySummaryViewModelTests`, `PlanOperationDTOTests`, этот файл.

- **Блокер: понедельник.** Сервер отдаёт `as_of = null` и для будущей недели, и для идущей, пока её первый день не закрыт. `WeekFormat.isRunning(_:at:)` теперь решает по календарю: неделя не завершена, её `startsOn` не позже дня сервера и `endsOn` не раньше него. Кнопка «Текущая» и ключ `current` идут через эту функцию (`isShowingRunningWeek`, запись кэша в `show`). Фикстуры согласованы по датам: `week(...)` и `runningWeek(iso:)` сдвигают `starts_on/ends_on`; `unclosedWeek(iso:)` даёт форму ответа понедельника и будущей недели. Красный тест первым ходом: `testOnMondayBeforeTheDayClosesTheCurrentWeekIsStillCurrent` падал на трёх проверках (кнопка, running, ключ `current`) до правки кода.
- **Решение «звать ли Today».** `VoiceDayDismissal.shouldReloadToday(after:)` — чистая функция, тест на оба исхода и на лист, который не открывался.
- **Лист собран через `sheet(item:)`** с `VoiceDaySession`; закрытие любым способом идёт через привязку и запоминает модель для `onDismiss`. На симуляторе первое открытие листа глазами не проверялось: UI-теста нет.
- Нит-правки: комментарий про тайм-аут (SDK повторяет, до ~360 с), `JournalOpDTO.mode` без ключа читается как `append`, оговорка про переход на летнее время в `serverDay`, шапка `RootView`.

## 2026-10-27 — PHASE-03/240

Экран «Добавки» (More → Добавки): список, добавление, «Принял» с работой без сети через общую очередь.

Тронуто 16 файлов. `new`: `Features/Supplements/{SupplementsFormat,SupplementsViewModel,SupplementsView}.swift`, `API/{APIClient,DTOs}+Supplements.swift`, тесты `SupplementsAPIClientTests`, `SupplementsViewModelTests`, `SupplementsFormatTests`. `mod`: `Cache/{OutboxQueue,OutboxReplay}.swift`, `API/APIClient+Outbox.swift`, `App/{AppNavigation,RootView}.swift`, `Features/{Today/TodayViewModel,Day/DayViewModel}.swift`, этот файл.

- **Очередь.** Новый случай `OutboxAction.markSupplementTaken` хранит id добавки и день нажатия, имени в нём нет (имя только в подписи `Принял: <имя>` для полосы «ждёт отправки»). Реплей идёт через `OutboxSupplementsAPI`; поле `OutboxReplay.supplements` необязательное, существующие вызовы не менялись. В `TodayViewModel` и `DayViewModel` добавлено только имя нового случая в два `switch`.
- **День нажатия.** Прямое нажатие день не шлёт: решает сервер. Нажатие из очереди шлёт `intake_date` по часам телефона со сменой суток в 04:00 (`SupplementsFormat.dayStartHour`). Сервер сверяет его со своим днём и отвечает 409, если день сменился. Запись уходит в «Не отправлено» с кнопкой «Записать в сегодня» (`forcedRetry` убирает дату).
- **Кэш списка** хранит день чтения: список из кэша за другой день не показывает «принято сегодня».
- **Логи.** Ни один файл фичи не пишет в лог; тест `testNoSupplementSourceWritesToALog` сканирует исходники.
- Не сделано: добавление без сети (нужен id с сервера), правка и архив добавок (тикет не просил), вёрстка на телефоне (#215).

### Слияние main (629b573: #235, #249, #240) в swarm/248

Конфликты были в четырёх местах: шапки `OutboxQueue.swift`, `DayViewModel.swift`, `TodayViewModel.swift` и этот файл. Код сошёлся без правок: случай `markSupplementTaken` из #240 стоит в `writesADay` («День») и в переключателе `TodayViewModel` как был; ветки #248 и #256 (черновик блокнота, `savedNotebooks`, кэш по ключу) его не затрагивают, потому что работают только с `saveNotebook`, `setDayMark` и чтениями дня. Отметка приёма добавки не заменяет старую того же target, не пишет `savedNotebooks`, не считается записью дня.

### PHASE-03/254, круг 1 (2026-10-27)

В diff 10 файлов. iOS, 7: `Features/HealthSync/{HealthKitSampleSource,HealthPump,HealthSyncView}.swift`, тесты `HealthPumpTests`, `HealthSampleMappingTests`, `HealthSyncViewModelTests` (`mod`), этот файл (`mod`). Вне iOS, 3: ADR-0020 (поправка A2, `mod`), `services/backend/tests/test_health_catalog_fixture.py` и `tests/fixtures/health/metric_catalog.json` (`new`).

- `HealthStoreQuerying: Sendable`; `FakeHealthStore` — `@unchecked Sendable` с обоснованием.
- Текст `.skipped` не обещает, что повторное нажатие поможет: тот же исход получает и iPad.
- Тест маппера читает `metric_catalog.json` по `#filePath`; бэкенд-тест держит файл равным `SEED_METRICS`. Если iOS-тест запустят вне дерева репозитория, он упадёт на чтении файла, а не пройдёт молча.
- Перевод `errorNoData` и живой пояс переделаны в круге 2.

### PHASE-03/254, круг 2 (2026-10-27)

Тронуто 8 файлов: `HealthKitSampleSource.swift`, `HealthPump.swift`, тесты `HealthPumpTests`, `HealthSampleMappingTests`, `HealthSyncViewModelTests`, ADR-0020 (`mod`), этот файл (`mod`).

- **ADR, блокер.** Абзац о смене пояса переписан: завышение вечное и касается всех дней окна, отправленных в старом поясе, и дискретных метрик без пояса семпла. Исправление вынесено в тикет #260. Добавлена оговорка про повторный час осеннего перевода: `sample_count` = 2, `min` и `max` — отдельные суммы.
- **`errorNoData`.** Перевод в пустой список переехал из `HKHealthStore.hourlySums` в `HealthPump.readWindow` (`hourlySumsOrEmpty`): двойник бросает ошибку, и тест проверяет связку. Пустое окно шагов не мешает отправке пульса покоя; любая другая ошибка даёт `.failed(.readFailed)`.
- **Пояс.** Насос открывает `calendar` и `mapper`, тест строит насос без аргументов и сравнивает с `autoupdatingCurrent` (отличим от `.current`). Статическая константа `deviceCalendar` убрана. В комментарии `readWindow` названа редкая гонка: смена пояса посреди прогона.
- **Единицы.** Копия списка серверных единиц в тесте маппера удалена: единицы сверяет тест фикстуры.

Мутации: возврат `.current` в календарь и подмена кода в `catch` валят по одному тесту (`testPumpBuiltWithoutZoneArguments…`, `testNoDataErrorOnTheStepWindow…`).

### PHASE-03/243 и PHASE-03/250: слияние main и замечания круга 2

Слит `main` (#235, #249, #240, #254). Конфликты только в шапках `App/AppNavigation.swift`, `App/RootView.swift` и в хвосте этого файла: оставлены обе стороны, держатели с токенами и строка «Добавки» (#240) целиком. Дополнительно тронуто: `Features/DailySummary/DailySummaryView.swift`, `Features/Week/{WeekFormat,WeekViewModel}.swift` (шапки), тесты `DailySummaryViewModelTests`, `WeekFormatTests`.

- **Повторное `nil` в привязку листа.** Состояние листа вынесено в `VoiceDayPresentation` (значение, без вида): `close()` идемпотентна и запоминает модель только пока лист есть. Закрытие во время `.applying`, затем успешный `onApplied` не стирают модель, и Today перечитывается. Тест `testClosingTwiceInARowDoesNotForgetTheFirstClose`.
- **Поздний `onApplied` старой модели** называет свою сессию (`VoiceDaySession` передаёт её через слабую ссылку), `close(ifShowing:)` закрывает только её лист. Тест `testTheLateAnswerOfAnOldSheetDoesNotCloseTheNewOne`.
- **`DailySummaryView.init(onApplied:)`** удалён вместе с фразами о нём в шапке: вызывающего не было, `retainer` теперь не опциональный.
- Граница понедельника 03:59 / 04:00 проверена в `WeekFormatTests`. `VoiceDaySession` оставлен `internal`: на него ссылаются тесты.
- Глазами в симуляторе лист не проверялся.

## 2026-10-29 — #265 iOS Life (More → Жизнь)

Файлы (new): `API/DTOs+Life.swift`, `API/APIClient+Life.swift`, `Features/Life/{LifeCalendar,LifeViewModel,LifeSquare,LifeView}.swift`, `HabitTrackerTests/Life{Calendar,ViewModel,APIClient}Tests.swift`. Файлы (mod): `App/AppNavigation.swift`, `App/RootView.swift` (добавлением), `README.md`.

Расхождения с `/m/life`:
- Квадрат дня и строка недели в вебе — ссылки на `/day/{date}` и `/week/{iso}`; в iOS экраны Day и Week не принимают дату снаружи (чужие файлы), поэтому квадрат открывает вид «день» внутри Life, ссылки «Открыть день/неделю» нет.
- Дата рождения — текстовое поле `ГГГГ-ММ-ДД` с проверкой (системный DatePicker не берём, своего календаря в iOS нет).
- Вид «жизнь» рисуется на Canvas; подсказок-tooltip нет, у квадратов есть подписи для VoiceOver.
- Рамка (дата рождения, лет) хранится в UserDefaults под тем же ключом, что у веба.

### PHASE-03/258: Добавки — правило дня сервера и хвосты #240

Тронуто 8 файлов (7 кода и этот файл): `API/APIClient+Supplements.swift`, `Cache/OutboxReplay.swift`, `Features/Supplements/{SupplementsFormat,SupplementsView,SupplementsViewModel}.swift` (mod), тесты `SupplementsFormatTests`, `SupplementsViewModelTests` (mod).

- **Правило дня.** `ServerDayRule` (пояс и час начала) приходит с сервера из окна `GET /week-review` (`fetchDayRule`), лежит в снимке кэша; день режется по настенным часам пояса сервера, а не вычитанием 4 часов абсолютного времени. Таймер на границу дня, смена часов и пояса перечитывают экран.
- **Ожидающее нажатие** другого дня не блокирует кнопку; `pressedAt` показан в строке «ждёт отправки · нажато ЧЧ:ММ».
- **Двойное нажатие.** Пока POST в пути, кнопка выключена (`isSending`).
- **Кэш.** Отброшенный старый ответ загрузки заменяется показанным списком.
- **`OutboxReplay.supplements`** не nil: по умолчанию `NoSupplementsAPI` (как мёртвая сеть), чужие вызывающие не менялись.
- **Заменяет записи #240.** `OutboxReplay.supplements` больше не необязательное (по умолчанию `NoSupplementsAPI`), а `SupplementsFormat.dayStartHour` удалён: день режет `ServerDayRule` по правилу сервера.
- Проверка вёрстки при крупном шрифте и VoiceOver на устройстве не делалась (#215).
### PHASE-01/216: ADR-0024 и экран «Цели» (2026-10-29)

Вариант A владельца: всё нативно. ADR-0024 в `docs/PHASE-01/ADRs/in-review/` заменяет пункты A1 и A5 ADR-0020. Экран Goals повторяет `components/goals/GoalsBoard.tsx`: уровни с «⚠ подтверди», милстоны со статусом, датой закрытия, кнопкой «Закрыть/Открыть» и чипами «Открывается чем», цели текущего квартала. Создания и правки целей в вебе нет (только `PATCH` статуса милстона), поэтому нет и в приложении. 8 файлов:

- new `API/DTOs+Goals.swift`, `API/APIClient+Goals.swift`
- new `Features/Goals/GoalsViewModel.swift`, `Features/Goals/GoalsView.swift`
- new `HabitTrackerTests/GoalsAPIClientTests.swift`, `HabitTrackerTests/GoalsViewModelTests.swift`
- mod `App/AppNavigation.swift` (case `.goals`), `App/RootView.swift` (строка `GoalsView()`)

Скриншот снят с экрана, встроенного в окно тестового хоста на симуляторе, с данными фикстуры; путь More → Цели касанием и живой бэкенд не проверялись.

## 2026-10-29 — #267 iOS Onboarding (More → Онбординг, лист первого запуска)

Файлы (new): `API/DTOs+Onboarding.swift`, `API/APIClient+Onboarding.swift`, `Features/Onboarding/{OnboardingMessages,OnboardingTemplatesModel,OnboardingPlanModel,OnboardingGate,OnboardingView}.swift`, тесты `HabitTrackerTests/Onboarding{Fixtures,APIClientTests,TemplatesModelTests,PlanModelTests,GateTests}.swift`. Файлы (mod): `App/AppNavigation.swift`, `App/RootView.swift` (добавлением: case, строка switch, один модификатор `.onboardingGate`), `README.md`.

Расхождения с `/m/onboarding`:
- В вебе автоматического перехода при первом запуске нет: онбординг предлагает пустое состояние Categories («Describe them instead»). В iOS добавлен лист первого запуска (один раз, когда сервер вернул ноль категорий; сбой чтения ничего не открывает и не помечает) и строка в «Ещё». Ссылка в пустом состоянии Categories не добавлена: `Features/Categories/**` не моё.
- После создания плана экран открывает Categories через `AppNavigation` (в вебе — `router.push`).
- Тексты ошибок 503/502/400/422 переведены в понятные фразы: клиент iOS не несёт тело ответа сервера, `detail` не показывается.
- Диктовки в вебе тоже нет, поле текстовое.
- Глазами проверен только лист с шаблонами на мок-сервере; план модели, применение и офлайн — тестами, не вручную. Настоящий ИИ не вызывался.
### PHASE-01/266: роли и правила разметки нативно (2026-10-29)

Файлы: new `API/DTOs+Roles.swift`, `API/APIClient+Roles.swift`, `Features/Roles/{RolesFormat,RolesViewModel,RoleRulesViewModel,RolesView,RoleRulesView}.swift`, тесты `Roles{Fixtures,FormatTests,APIClientTests,ViewModelTests}`; mod `App/AppNavigation.swift`, `App/RootView.swift` (строка «Роли»), `README.md`.

Расхождения с мобильным вебом:
- Правило нельзя удалить: у сервера нет `DELETE /role-rules`. «Удалить» и «изменить» сведены к переключателю `is_active` (`PATCH`); правка образца, роли и веса существующего правила не сделана — в вебе её тоже нет.
- Записи ролей (минуты, акт, подтверждение, «убрать», правила, переразметка) идут только при сети, в офлайн-очередь не попадают: у веба очереди нет, а запись не идемпотентна. Чтение — через кэш с пометкой «Offline».
- Пятничный отчёт копируется в буфер кнопкой «Скопировать» (`UIPasteboard`).
- Не проверено: экран в приложении на симуляторе через More (скриншот снят из окна теста с тестовым API), живой сервер.
## 2026-10-29 — PHASE-03/263: остатки ревью #248/#256 (День и Today)

Тронуто (`mod`): `Cache/OutboxQueue.swift`, `Features/Day/DayViewModel.swift`, `Features/Today/TodayViewModel.swift`, `Features/Today/TodayView.swift`, тесты `DayOfflineTests`, `DayViewModelTests`, `TodayViewModelTests`.

- **Судьба сохранения блокнота.** `OutboxQueue.enqueue` возвращает `id` записи. `saveNotebook` после `flush` ищет в очереди эту запись, а не любую того же `target`: отказанная запись того же дня больше не мешает записать `savedNotebooks` для доставленной.
- **Today.** `failLoad` получает номер загрузки (`loadsSent`/`loadShown`, отдельно от чтений записей) и молчит, только если более новая загрузка уже дошла до `.loaded`. Первая загрузка без более новой при сбое даёт `.failure`, даже если тихое перечитывание записей успело (круг 2: раньше сверка шла с номером чтения записей и могла оставить `.loading` навсегда). Пустой экран («нет категорий») показывает строку сбоя обновления.
- **`newestCached`.** При вытеснении ключ, только что записанный ответом, не удаляется.
- **Шапки.** `OutboxQueue.swift`, `DayViewModel.swift`, `DayOfflineTests.swift` описывают очередь с `mayHaveLanded: true` при 502/504 вместо перечитывания; круг 2 #248/#256 стоит рядом с кругом 1.
- **Тесты.** `NotEqual` заменены сравнением с текстом сервера; путь «Оставить мой» для третьего текста; ошибка другого действия вызывает настоящее упавшее сохранение; два параллельных `load()` (поздний сбой L1); отказанная запись того же дня при доставленном сохранении (мутация условия на `target` валит тест).

Проверки: см. сдачу. Не проверено: экран глазами на симуляторе.

## 2026-10-30 — #222 анимированный обзор недели

Файлы: `Features/Week/WeekOverviewModel.swift` (new), `Features/Week/WeekOverviewView.swift` (new), `Features/Week/WeekView.swift` (mod, кнопка «Итоги недели» и sheet), `HabitTrackerTests/WeekOverviewTests.swift` (new). Данные только из `GET /week-review`; при «Уменьшить движение» числа и столбцы сразу стоят в конечном виде. Не проверено: вживую в приложении (вход через Ещё → Неделя, свайп слайдов, сама анимация); снимки — отрисовка `ImageRenderer` в симуляторе.

## 2026-10-30 — #270 вход в Day и Week по дате, ссылки из Life, остатки #265

Файлы (13, все mod): `App/AppNavigation.swift`, `App/RootView.swift`, `Features/Day/DayViewModel.swift`, `Features/Week/WeekView.swift`, `Features/Week/WeekViewModel.swift`, `Features/Life/LifeCalendar.swift`, `Features/Life/LifeViewModel.swift`, `Features/Life/LifeView.swift`, тесты `AppNavigationTests`, `DayViewModelTests`, `LifeCalendarTests`, `LifeViewModelTests`, `WeekViewModelTests`.

Проверки: сборка `build-for-testing` зелёная; тесты не запускались (симулятор не использовался). Не проверено: переходы глазами.

## 2026-10-30 — #274 остатки ревью #270

Файлы (11, все mod): `App/AppNavigation.swift`, `App/RootView.swift`, `Features/Day/DayFormat.swift`, `Features/Day/DayView.swift`, `Features/Day/DayViewModel.swift`, `Features/Life/LifeCalendar.swift`, `Features/Life/LifeView.swift`, `Features/Life/LifeViewModel.swift`, тесты `AppNavigationTests`, `DayViewModelTests`, `LifeViewModelTests`. Одна загрузка при переходе в Day (общая задача на день), будущая дата рождения из хранилища отвергается, `isWeekCode` знает недели года. Тесты не запускались; переходы глазами не проверены.

## 2026-10-30 — #238 сон из HealthKit

Файлы (10, все mod): `API/DTOs+Health.swift`, `Features/HealthSync/HealthDataReader.swift`, `HealthKitSampleSource.swift`, `HealthMetricCatalog.swift`, `HealthPump.swift`, `HealthSyncView.swift`, тесты `HealthAPIClientTests`, `HealthPumpTests`, `HealthSampleMappingTests`, `HealthSyncViewModelTests`. Насос читает сон сырыми интервалами с 18:00 накануне окна и шлёт их `category_samples` в том же чанке и прогоне; разрешение на сон — в одном листе с остальными. Точка журнала #273 в `HealthPump.swift` не сдвинута (`joinOrStart`/`run` прежние). Проверки: полный прогон 950/0 на sw-132. Не проверено: на устройстве с настоящими данными сна (#215).
