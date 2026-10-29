# HabitTracker для iOS

Проект собирает XcodeGen из `project.yml`, `HabitTracker.xcodeproj` в git не хранится. После правки `project.yml` или добавления файла запусти `xcodegen generate` в этой папке.

```bash
xcodegen generate
xcodebuild test -project HabitTracker.xcodeproj -scheme HabitTracker \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro'
```

Тесты Keychain и Settings проходят только с обычной подписью симулятора. С `CODE_SIGNING_ALLOWED=NO` они падают с `KeychainError(status: -34018)`: у неподписанной сборки нет доступа к Keychain. Подпись симулятора — «Sign to Run Locally», входа в аккаунт она не требует.

## Правила для тикетов экранов

Тикеты экранов идут параллельно и не правят общие файлы. Общие файлы — `App/**`, `API/APIClient.swift`, `API/DTOs.swift`, `project.yml`, `Info.plist`, entitlements.

1. Экран живёт в своей папке `Features/<Фича>/`. Свой `NavigationStack` экран не заводит: стек даёт вкладка или More в `App/RootView.swift`. Sheet по-прежнему держит свой стек внутри.
2. Протокол и запросы фичи пиши в `API/APIClient+<Фича>.swift` как `extension APIClient: <Фича>API`. Внутренние помощники `getJSON`, `sendJSON`, `send`, `makeAPIURL`, `makeRequest` доступны из любого файла модуля. Поток байтов, например SSE чата, открывай через `session.bytes(for: makeRequest(...))`.
3. Существующий протокол расширяй наследником в своём файле (`protocol TodayScreenAPI: TodayAPI`). `APIClient.swift` не правь.
4. DTO фичи клади в `API/DTOs+<Фича>.swift`. `DTOs.swift` и `APIJSONCoding` не правь.
5. Клиент бери из `APIClient.live()`, для медленного запроса — из `APIClient.live(timeout:)`. Ручной `APIClient(` в `Features/` не проходит ревью.
6. Заглушку своего экрана заменяй целиком. Оставь у замены `init()` без аргументов: view model она собирает сама через `.live()`, и тогда `RootView` не меняется.
7. Переход на другой экран делай через `AppNavigation.open(.tab(...))` или `.open(.more(...))`.
8. Если без общего файла не обойтись, правь его только добавлением: строка в `RootView`, свой ключ в `project.yml`. Строки для микрофона, распознавания речи, Face ID и entitlement фоновой доставки HealthKit уже стоят.
9. Тесты пиши в своём файле в `HabitTrackerTests/`.

| Заглушка или место | Тикет |
| --- | --- |
| `Features/QuickMarks/QuickMarksView.swift`, вкладка Today | #210 |
| `Features/Day/DayView.swift` | #211 |
| `Features/Chat/ChatView.swift` | #212 |
| `Features/DailySummary/DailySummaryView.swift` | #213 |
| экран блокировки: модификатор `.appLock()` в `HabitTrackerApp` | #214 |
| `Features/HealthSync/`, вкладка Health | #131 |
| `Features/Life/LifeView.swift`, More → Жизнь | #265 |
| `Features/Goals/`, строка «Цели» в More | #216 |
| `Features/Onboarding/OnboardingView.swift`, More → Онбординг и лист первого запуска (`.onboardingGate` в `RootView`) | #267 |
| `Features/Roles/`, More → Роли (и правила разметки внутри) | #266 |

## Решение: цифры здоровья лежат в общем кэше чтения (#243, 2026-10-27)

Экран «Неделя» кладёт ответ целиком, вместе с блоком `health` (среднее в день по шагам и тренировкам, значения по дням), в общий кэш чтения `ReadThroughCache` → `SwiftDataCacheStore` (таблица `CacheRecord` в песочнице приложения). Отдельного хранилища для здоровья нет.

Почему так. В тот же кэш уже попадают записи за день, тексты дневника и категории, и они чувствительнее недельных средних. Второе хранилище не добавило бы защиты: оно лежало бы в той же песочнице с тем же классом защиты файла. Сырых образцов HealthKit в кэш не попадает: `HealthSync` отправляет их на сервер и у себя не хранит.

Границы решения. Класс защиты файла не задан явно, действует умолчание iOS «до первой разблокировки». Резервная копия устройства кэш включает. Если появятся сырые образцы HealthKit в кэше или понадобится шифрование на диске, здоровье выносят в отдельное хранилище. Тогда это новый ADR.

## Установка на телефон

Исходная точка: Mac с Xcode 26, телефон сопряжён с Mac и виден в `xcrun devicectl list devices`.

1. Открой Xcode → Settings → Accounts и войди под Apple ID команды `BU56H2G49W`. Проверка: в списке команд аккаунта видна «Personal Team». Профили других команд в связке ключей для этого приложения не подходят.
2. Разблокируй телефон и подключи его кабелем или к той же сети Wi-Fi, что и Mac. Developer Mode должен быть включён: Настройки → Конфиденциальность и безопасность → Режим разработчика.
3. Выполни из папки `habit-tracker`:

   ```bash
   make ios-device IOS_DEVICE=<id телефона>
   ```

   `id` возьми из `xcrun devicectl list devices`. Без `IOS_DEVICE` команда напечатает список и остановится: с Mac сопряжено несколько iPhone, поэтому устройства по умолчанию нет. Ожидаемый результат — строка «Готово: HabitTracker установлен». При ошибке скрипт называет шаг, на котором остановился.
4. При первом запуске подтверди разработчика на телефоне: Настройки → Основные → VPN и управление устройством → «Доверять».
5. Включи на телефоне Tailscale в той же сети, что и сервер.
6. В приложении открой More → Settings, введи адрес сервера по Tailscale и ключ API, нажми «Check connection». Проверка: зелёная галочка.

Ограничения Personal Team (бесплатная команда): профиль действует 7 дней, потом повтори `make ios-device`. Если Xcode отвечает, что идентификатор `com.daniilbystrov.habittracker.HabitTracker` недоступен, задай свой: `make ios-device IOS_DEVICE=<id> IOS_BUNDLE_ID=com.<имя>.habittracker`. Поддерживает ли Personal Team HealthKit и его фоновую доставку, не проверено: это покажет шаг подписи.
