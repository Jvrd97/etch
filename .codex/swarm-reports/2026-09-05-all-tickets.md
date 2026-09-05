# Запуск issue-swarm — 2026-09-05

Запрос: выполнить все тикеты. Источник очереди — метаданные локальных тикетов.

NO-CODE: обычный день. Коммиты и push не выполняются. Существующие правки сохраняются.

## Очередь

| Тикет | Режим | Зависимости | Состояние на старте |
| --- | --- | --- | --- |
| [№14](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/14-testflight-release.md) | Участие человека | [#02, #05, #06] | backlog |
| [№49](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/49-device-acceptance-checklist.md) | Участие человека | 40, 41, 42, 43, 44, 45, 46, 47, 48 | backlog |
| [№65](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-02/backlog/65-health-full-metric-catalog.md) | Автономно | 64 | backlog |
| [№66](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-02/backlog/66-health-year-backfill-chunks.md) | Участие человека | 64 | backlog |
| [№67](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-02/backlog/67-health-rolling-window-on-launch.md) | Участие человека | 64 | backlog |
| [№68](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-02/backlog/68-health-metric-detail-hourly.md) | Автономно | [PHASE-03/#131] (страница `/health` и данные на ней) | backlog |
| [№69](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-02/backlog/69-health-sparklines-and-baseline.md) | Автономно | 65, [PHASE-03/#131] (список метрик `/health`, куда спарклайн встаёт) | backlog |
| [№70](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-02/backlog/70-health-workouts.md) | Участие человека | [PHASE-03/#131] (насос HealthKit: разрешения, чтение, отправка чанка) | backlog |
| [№71](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-02/backlog/71-health-sleep-phases.md) | Участие человека | [PHASE-03/#131] (насос HealthKit: разрешения, чтение, отправка чанка) | backlog |
| [№72](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-02/backlog/72-health-sync-status-screen.md) | Участие человека | 66 (курсор бэкфилла, который эта кнопка сбрасывает), [PHASE-03/#131] (экран синка, на котором кнопка живёт) | backlog |
| [№76](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/76-dashboard-recent-activity-feed.md) | Автономно | 73, 75 | backlog |
| [№77](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/77-structured-ai-report-and-summary-block.md) | Участие человека | none | backlog |
| [№78](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/78-dashboard-trends-block.md) | Автономно | 75 | backlog |
| [№79](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/79-stats-endpoint-and-summary-bar.md) | Автономно | 74 | backlog |
| [№80](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/80-app-settings-icons-quick-access-english.md) | Автономно | 73 | backlog |
| [№81](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/81-llm-fills-full-category-styling.md) | Участие человека | 75, 80 | backlog |
| [№82](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/82-llm-groom-existing-categories.md) | Участие человека | 81 | backlog |
| [№83](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/83-daily-summary-plan-fields-required.md) | Автономно | none | backlog |
| [№95](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/95-skills-over-api-day-job-and-decommission.md) | Участие человека | [#89], [#91], [#92], [#93], [#94], [#108] (единственный планировщик фоновых задач) | backlog |
| [№99](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/99-inbox-worker-and-schedule.md) | Автономно | 108 (процесс воркера, реестр заданий и блокировка), 97, 98 | backlog |
| [№100](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/100-inbox-gmail-adapter.md) | Участие человека | 97 (готов), 98 (карточка источника и хранилище ключей — готовы; редактор allowlist доезжает в [#186]) | backlog |
| [№101](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/101-inbox-llm-commitments.md) | Автономно | 97, 100 | backlog |
| [№102](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/102-inbox-telegram-telethon-read-only.md) | Участие человека | 108 (постоянный клиент живёт в цикле единого воркера), 98, 99, 101 | backlog |
| [№103](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/103-inbox-mirror-complete-to-clickup.md) | Автономно | 97 | backlog |
| [№104](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/104-inbox-privacy-contract-and-retention.md) | Автономно | 108 (планировщик, в котором живёт суточное задание), 99, 101 | backlog |
| [№105](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/105-inbox-source-observability.md) | Автономно | 97 (заготовка источника `clickup/alvion` в справочнике), 98, 99 | backlog |
| [№119](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/119-chat-prod-preconditions-oauth-volume-timeout.md) | Участие человека | 120 (а через него — 111). Порядок именно такой: этот тикет снимает монтирование хостового `~/.claude`, а три существующих юзкейса `generate` переживают это снятие только после общей сборки аргументов CLI из 120 | backlog |
| [№131](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/131-healthkit-pump-and-desktop-health.md) | Участие человека | [PHASE-02/done/64-health-vertical-two-metrics.md] — серверная половина (`POST /health/samples`, `app/health/aggregate.py`, `GET /health/metrics`) отгружена и закрыта | backlog |
| [№132](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/132-health-sync-run-journal-and-lag.md) | Автономно | [#131] | backlog |
| [№133](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/133-healthkit-background-delivery-queue.md) | Участие человека | [#131], [#132] | backlog |
| [№136](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/136-classify-day-signals-commits-and-clickup-into-roles.md) | Автономно | [#134] (правила, `role_time_block`, `role_act`), [#146] (`day_signal`: коммиты и события ClickUp уже доезжают до базы) | backlog |
| [№146](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/146-day-signal-commits-and-clickup.md) | Участие человека | [#86], [#142], [#145] | backlog |
| [№149](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/149-plan-job-background-runner.md) | Автономно | [#95] (`day_job`, кнопка «Сделать план на завтра», статус и лог), [#108] (единственный планировщик — раннер живёт в нём, своего процесса тикет не заводит), [#148] (генерация внутри процесса) | backlog |
| [№153](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/153-skills-over-api-and-personal-os-decommission.md) | Участие человека | [#95] (скиллы переписаны на HTTP, `plan_server.py` выведен), [#142] (полная карта дня в правиле), [#152] (экран правил) | backlog |
| [№155](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/155-mac-agent-first-interval-skeleton.md) | Автономно | none | backlog |
| [№156](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/156-mac-agent-accessibility-permission.md) | Участие человека | 155 | backlog |
| [№157](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/157-mac-agent-window-titles-privacy-rules.md) | Автономно | 155, 156 | backlog |
| [№159](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/159-floating-panel-task-and-timer.md) | Автономно | 155, 87 (задача дня и страница дня: без них `/agent/config` нечего отдавать, а кнопке «открыть в браузере» некуда вести) | backlog |
| [№162](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/162-day-mode-schedule-and-override.md) | Автономно | 155, 87 (страница дня, на которой стоит бейдж режима и переключатель) | backlog |
| [№163](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/163-agent-disk-queue-and-backoff.md) | Автономно | 155 | backlog |
| [№164](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/164-agent-heartbeat-and-web-banner.md) | Автономно | 163 | backlog |
| [№165](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/165-claude-code-session-metrics.md) | Автономно | 155, 163 | backlog |
| [№166](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/166-intervals-link-to-day-tasks-and-closing.md) | Автономно | 160, 87, 91, 143 | backlog |
| [№167](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/167-agent-packaging-and-login-item.md) | Участие человека | 155, 159 | backlog |
| [№168](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/168-agent-settings-screen.md) | Автономно | 167 | backlog |
| [№169](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/169-agent-docs-and-xcodebuild-feedback-loop.md) | Автономно | 167 | backlog |
| [№170](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/170-quick-marks-in-floating-panel.md) | Автономно | 159, 125 (контракт `surface=agent` и переключатель `show_in_agent`) | backlog |
| [№171](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/171-vscode-file-history-behind-flag.md) | Автономно | 157 | backlog |
| [№172](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/172-agent-energy-idle-and-sleep.md) | Автономно | 155, 163 | backlog |
| [№174](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/174-bulk-streaks-endpoint-and-dashboard-block.md) | Автономно | none | backlog |
| [№175](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/in-work/175-category-primary-field-explicit.md) | Автономно | none | in-work |
| [№176](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/176-field-unit-quick-steps-continue-tracking.md) | Автономно | none | backlog |
| [№177](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/177-today-day-entries-list.md) | Автономно | [#63] | backlog |
| [№178](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-01/backlog/178-builtin-category-templates.md) | Автономно | none | backlog |
| [№180](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/180-one-reclassify-promise-and-one-confirmed-predicate.md) | Автономно | none — обе ручки закрыты ([#135], [#139]), работа идёт поверх готового кода | backlog |
| [№181](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/181-alembic-chain-against-a-lived-in-database.md) | Автономно | none — обе упавшие ревизии уже починены (`1ddbe2b`, `3c50a50`), работа идёт поверх них | backlog |
| [№182](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/182-live-cli-smoke-actually-runs.md) | Автономно | none на маке. [#119] — для того же прогона на сервере | backlog |
| [№183](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/183-prod-contour-runs-at-least-once.md) | Участие человека | none по коду. Поднятый docker — за человеком | backlog |
| [№184](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/184-background-plan-generation-what-is-left-of-149.md) | Автономно | [#95] (таблица `day_job`, кнопка и опрос статуса) — в backlog, не начат. [#108] и [#148] закрыты | backlog |
| [№185](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/185-one-day-boundary-and-one-constant.md) | Автономно | none — [#107] закрыт, здесь его же инвариант доводится до конца | backlog |
| [№186](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/issues/PHASE-03/backlog/186-inbox-work-mailbox-and-label-allowlist.md) | Участие человека | 100 (адаптер Gmail), 98 (карточка источника — готова) | backlog |

## Результаты

### №175 — PASS

Проверен за 2 раунда и перенесён в основную рабочую копию без коммита. Изменено 17 файлов. Бэкенд: 1575 тестов прошли, 3 пропущены. Интерфейс: 1403 теста прошли. После переноса: 65 тестов бэкенда и 38 тестов интерфейса прошли; типы, стиль, Alembic и diff — успешно.

Отчёт: [175.md](/private/tmp/habit-issue-175/.claude/loop-reports/175.md). Lifecycle сохранён: in-work. Блокеров нет.

### №65 — PASS

Проверен за 2 раунда и перенесён в основную рабочую копию без коммита. Изменено 20 файлов. Бэкенд: 51 тест, стиль, типы и сценарии миграции прошли. Интерфейс: 2 теста, типы и стиль прошли. iOS: сборка и XCTest прошли. Проверки после переноса подтверждают полный patch и одну голову Alembic. Изменения №175 сохранены.

Lifecycle сохранён: backlog. Блокеров нет; №69 всё ещё зависит от №131. Относительный путь отчёта owner: `.claude/loop-reports/65.md`.

### №76 — BLOCKED

Preflight нашёл дополнительную техническую зависимость от №176: поле `Field.unit` отсутствует, поэтому обязательное значение с единицей пока не реализовать. Код не менялся. Вернуться после №176.

Отчёт: [76.json](/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/.Codex/loop-reports/76.json).

### №176 — следующий

Перенесён вперёд очереди, чтобы разблокировать №76. Итоговые проверки и ревью ещё не выполнены.
