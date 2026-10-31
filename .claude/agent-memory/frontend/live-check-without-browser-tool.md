---
name: live-check-without-browser-tool
description: Как проверить интерфейс вживую, когда у агента нет браузерного инструмента — headless Chrome, CDP по WebSocket из Bun, ловушки view-mode и порядок линковки mock-модулей в bun test
metadata:
  type: reference
---

Роевому исполнителю браузерный инструмент не выдан, но `/Applications/Google Chrome.app` есть.

- Запуск: `Google Chrome --headless=new --remote-debugging-port=<свой порт> --user-data-dir=<папка в scratchpad>`. Дальше `PUT /json/new?<url>` и WebSocket из Bun без зависимостей: `Page.navigate`, `Emulation.setDeviceMetricsOverride` (390×844, `mobile: true`), `Emulation.setTouchEmulationEnabled`, `Input.dispatchMouseEvent` по центру элемента (так в проверку попадает перекрытие), `Page.captureScreenshot`, затем `Read` по png.
- Профиль браузера помнит `localStorage['habit-tracker:view-mode']`: после захода на `/m/*` холодный старт `/today` перебрасывает на `/m/today` даже в окне 1280. Для десктопа перед проверкой записать `desktop` и `sessionStorage['habit-tracker:view-mode-restored']='1'`.
- Скриншот сразу после появления листа ловит `animate-fade-rise` на середине (лист полупрозрачный). Перед снимком подождать 1 с.
- `performance.getEntriesByType('resource')` до и после действия показывает, сколько запросов стоил тап.
- В `bun test` один процесс на все файлы: `mock.module('@/lib/api', …)` фиксирует имена экспортов. Новому тестовому файлу безопаснее `mock.module('@/lib/api', () => ({ ...realApi, quickMarksAPI: {…} }))`, где `realApi = await import('@/lib/api')` до мока. Тогда его мок не отнимает экспорты у следующих файлов.
- `app/m/health/page.test.tsx` в полном прогоне красный или зелёный в зависимости от порядка линковки; в изоляции зелёный.
- Бэкендовые `tests/test_goals.py` (2 теста) падают, когда текущий квартал не 2026-Q3: цели берутся по текущему кварталу, фикстура лежит в Q3.
