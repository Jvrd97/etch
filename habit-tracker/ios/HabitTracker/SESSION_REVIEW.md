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
