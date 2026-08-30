# Проверка переноса issue-loop и issue-swarm в habit_tracker_ai

Дата проверки: 2026-08-30. Проверял только `.claude/workflows/`; `habit-tracker/`, `issues/`
и worktree `phase03-b` не трогал.

**Вердикт: петля рабочая, запускать можно.** Восемь пунктов проверки прошли. Три дефекта
нашлись, ни один не мешает первому прогону: один в логике swarm (тикет поедет поверх
непостроенного блокера), один в формулировке SCOPE (агент может отказаться открыть тикет),
один в данных бэклога (два тикета отсеются зря).

---

## 1. Синтаксис

```
node --check issue-loop.js   → OK
node --check issue-swarm.js  → OK
```

## 2. Запрещённое в Workflow-скриптах

`grep` по обоим файлам: `Date.now`, `Math.random`, `new Date`, `import`, `require`, `fs.`,
`process.`, `__dirname`, `globalThis` — **ноль совпадений**.

Дата в отчёте берётся правильным способом: `REPORT_PROMPT` просит агента выполнить
`date +%F` и `date -u +%FT%TZ` в bash, а не считать её в скрипте.

Корень репозитория и путь к `issue-loop.js` вшиты абсолютными строками с переопределением
через `args.repoRoot` / `args.loopScript` — обход отсутствия `process.cwd()`, а не
обращение к файловой системе.

## 3. meta

`issue-swarm`: `phases` = Triage, Swarm. Вызовы `phase()` = Triage, Swarm. **Совпадает.**

`issue-loop`: `phases` = Preflight, Plan, Implement, Simplify, **Review**, Verdict, Report.
Вызовы `phase()` = Preflight, Plan, Implement, Simplify, Verdict, Report — `phase('Review')`
отдельной строкой нет. Три ревью помечены через `phase: 'Review'` в опциях `runAgent`
(строки 712-714), поэтому фаза в трассировке появляется.

Это не регресс переноса: в оригинале `alv/.claude/workflows/issue-loop.js` ровно то же
самое — `Review` объявлен в `meta`, а голого `phase('Review')` нет. Перенесено дословно.

## 4. Пути и команды

Все существуют, кроме двух, и оба отсутствия — намеренные:

| Путь | Статус |
|---|---|
| `habit-tracker/services/backend`, `.../frontend`, `.../frontend/tsconfig.json`, `package.json` | есть |
| `habit-tracker/ios`, `habit-tracker/ARCHITECTURE.md` | есть |
| `.claude/skills/implement-issue.md` | есть |
| `.claude/skills/senior-python-backend/SKILL.md` | есть |
| `.claude/agents/reviewer.md`, `.claude/agents/simplifier.md` | есть |
| `~/.claude/skills/antivibe/SKILL.md`, раздел `## Gate Mode (--gate)` | есть, строка 162 |
| `graphify-out/graph.json` | есть |
| `docs/PHASE-03/ADRs/in-review/ADR-0014-day-in-postgres.md` | есть |
| `.claude/CLAUDE.md`, секции §2 §3 §4 §5 §8 §9 | есть, номера и темы совпадают со ссылками в скрипте |
| `.claude/loop-reports/` | нет — `REPORT_PROMPT` велит агенту создать каталог |
| `habit-tracker/mac` | нет — скрипт сам это оговаривает и запрещает туда работать |

`docs/PHASE-*/architecture/**` из `ALIGNMENT_PROMPT` матчится только на `PHASE-01/architecture`;
для PHASE-03 такого каталога нет. Глоб просто вернёт меньше, ошибки не будет.

### Команды проверок прогнаны на живом репозитории

Из корня репозитория, форма — дословно из `BACKEND_CHECKS`:

```
uv run --directory habit-tracker/services/backend ruff check app tests
  → All checks passed!
uv run --directory habit-tracker/services/backend ruff format --check app tests
  → 99 files already formatted
uv run --directory habit-tracker/services/backend mypy --strict app
  → Success: no issues found in 73 source files
uv run --directory habit-tracker/services/backend alembic heads
  → e0b2d4f6a8c1 (head)      ← ровно одна голова
```

Флаг `--directory` действительно переносит рабочий каталог: относительные `app tests`
разрешились правильно, `cd` не понадобился.

Фронт, дословно из `FRONTEND_CHECKS`:

```
bunx tsc -p habit-tracker/services/frontend/tsconfig.json --noEmit
  → exit 0, пустой вывод
```

Версия tsc, которую поднимает `bunx` из корня репозитория (5.9.3), совпадает с локальной
в `frontend/node_modules` (5.9.3) — конфликта версий нет. `bun --cwd=<abs>` — валидный флаг
(`bun --help`: «Absolute path to resolve files & entry points from»), проверен на
`bun --cwd=... pm ls`. `bun test` не гонял.

### Факты окружения подтверждены

```
docker info          → демон не работает
порт 5432            → открыт
порт 5433            → закрыт
```

Обход через `env`-префикс зашит правильно. `Bash(env *)` в allow-списке действительно
есть — `.claude/settings.local.json:99`. Там же `Bash(uv run *)`, `Bash(bun *)`, `Bash(bunx *)`.

**Оговорка:** `settings.local.json` лежит в `.gitignore`. На свежем клоне репозитория
`Bash(env *)` не будет, и команда с env-префиксом повиснет на permission-промпте —
ровно то, от чего предостерегает комментарий в строках 110-112.

## 5. Разбор тикета

Логика разбора живёт не в коде, а в промптах (`TICKET_FORMAT` в петле, `TRIAGE_PROMPT`
в swarm). Прогнал её правила вручную по
`issues/PHASE-03/backlog/90-day-summary-evaluate-day-and-streak.md`:

```json
{
  "id": "90",
  "title": "Итог дня и вердикт: `day_summary`, чистая `evaluate_day` и пересчёт стрика",
  "type": "AFK",
  "typeReason": "",
  "blockedBy": ["88", "89"],
  "estimated": "M",
  "adr": "ADR: `docs/PHASE-03/ADRs/in-review/ADR-0014-day-in-postgres.md` (Р2, Р8)"
}
```

Статусы блокеров по глобу `issues/PHASE-*/*/N-*.md`: `88 → PHASE-03/done`,
`89 → PHASE-03/backlog`. То есть #90 ждёт #89 — swarm это и посчитает.

Регулярка `issueId` из строки 758-760 прогнана по всем 78 именам файлов бэклога:
**все 78 дали чистый номер**, сбоев нет. Расширение под цифровой префикс (`*` вместо `+`
в альфа-сегменте) работает.

Поля `**Type**` и `**Estimated**` нашлись у всех 78 тикетов. Типы в бэклоге ровно два:
`AFK` и `human-in-the-loop`.

## 6. Отбор кандидатов в issue-swarm

Прогнал логику отбора и волн на всём `PHASE-03/backlog` (78 тикетов на входе).
**Список непустой и осмысленный: 64 тикета runnable, 14 отсеяно.**

Отсеяны как `human-in-the-loop`: #95 #97 #100 #102 #119 #131 #133 #146 #153 #156 #167 —
причины в скобках реальные (токен ClickUp, OAuth в браузере, разрешение HealthKit,
подтверждение в «Объектах входа»).

Отсеяны по открытым блокерам:

- **#123** — блокер 174 лежит в `PHASE-01/backlog`. Отсев правильный.
- **#129, #151** — отсев ошибочный, см. дефект C ниже.

Волны по зависимостям: 13 → 21 → 17 → 6 → 5 → 2. При `concurrency = 1` тикеты идут
по одному, порядок внутри волны — порядок массива.

**Первая волна (с чего swarm начнёт прямо сейчас):**

| # | Тикет |
|---|---|
| 89 | Импорт истории personal-os: CLI, `legacy_key`, `import_source` и обратный экспортёр |
| 98 | Входящие: экран источников и allowlist |
| 101 | LLM-разбор в обязательства |
| 103 | Отметка «сделано» уходит обратно в личный ClickUp |
| 108 | Один планировщик фоновых задач |
| 109 | Сессия для веб-клиента: HttpOnly-кука |
| 111 | Чат отвечает одним ходом: изолированный CLI, SSE |
| 121 | Быстрая отметка: справочник `quick_marks` + эндпоинт |
| 132 | Журнал синков `health_sync_run` |
| 134 | Роли становятся данными |
| 155 | Агент: первый интервал активности |
| 168 | Экран настроек агента |
| 169 | Документация агента и `xcodebuild test` |

Два из них — #168 и #169 — попали в первую волну ошибочно, см. дефект A.

## 7. Агенты и скиллы

Единственный `agentType` в петле — `simplifier` (строка 706).
`.claude/agents/simplifier.md` есть, `name: simplifier` во frontmatter совпадает,
в `tools` есть `Edit` и `Bash` — править и откатывать он может.

Скиллы, названные в промптах: `implement-issue`, `senior-python-backend`, `antivibe`
(глобальный, `~/.claude/skills/`). Все три на месте. `reviewer.md` упомянут как роль
в тексте промпта, без `agentType` — файл существует.

## 8. Что осталось за бортом относительно alv

Сверил построчно списки объявлений верхнего уровня в обоих файлах.

**Убрано осознанно, оговорено в шапке скрипта:**

- `deriveService()`, `KNOWN_SERVICES`, `ID_PREFIX_TO_SERVICE` — тикеты вертикальные,
  выводить сервис не из чего;
- фаза `Archify` вместе с `ARCHIFY_SCHEMA`, `ARCHIFY_PROMPT`, `archJson`, `archHtml` —
  ни одного `.archify.json` и каталога `docs/architecture/` в репозитории нет;
- `night-report.js` и путь `.dsh/watcher/reports/` — каталогов нет, вместо них
  `.claude/loop-reports/<id>.{json,md}`, которые пишет сам агент фазы Report.

**Молча потерянного нет.** Все схемы, промпты, тело цикла, обработка `null`-агентов,
`NEEDS_DISCUSSION`, красных loops и `maxRounds` перенесены один в один. Часть усилена:
`feedbackLoops` разбит по слоям вместо плоского `{lint, types, tests}`, добавлен
`moduleMapDelta` в `PLAN_SCHEMA`, добавлены `ticketTitle/ticketType/typeReason/blockedBy/adr/layers`
в `PREFLIGHT_SCHEMA`, `renderedPath` в `REPORT_SCHEMA`.

`issue-swarm` переписан почти целиком: в alv он раскидывал петли по сервисам параллельно,
здесь считает зависимости по `**Blocked by**` и гонит волнами. Фаза `Triage` — новый код,
в alv её нет.

Одна деталь alv, которая не доехала и, похоже, зря: в alv `SCOPE_TEXT` содержал явное
«Не открывай, не grep'ай и не glob'ай другие сервисы и каталоги репо». Здесь запрет
переформулирован в deny-список каталогов, и из-за этого получился дефект B.

---

## Дефекты

### A. Тикет едет поверх блокера, которого никто не построит

`issue-swarm.js`, строки 127-140.

Порядок операций: сначала `human-in-the-loop` выбрасываются в `dropped`, потом
`idsInRun` собирается **из уцелевших** `runnable`, и `deps` фильтруются по нему.
Блокер, выброшенный как `human-in-the-loop`, исчезает из зависимостей вместо того,
чтобы утащить зависимый тикет за собой.

Триаж-агент тут ни при чём: его инструкция «в `openBlockers` клади те, кого нет среди
тикетов ЭТОГО ПРОГОНА» отработала верно — блокер в прогоне был, его выбросили позже.

Что происходит на живом бэклоге:

- #168 и #169 заблокированы на #167 («перезагрузка мака и подтверждение в Объектах входа»).
  #167 выброшен как `human-in-the-loop`, и оба уезжают в **первую же волну**;
- #99 заблокирован на #97 (личный токен ClickUp) — уезжает во вторую волну.

Три тикета начнут работу на несуществующем фундаменте.

Починка: считать `idsInRun` по исходному списку `issues`, а не по `runnable`, и добавить
выброшенные id в множество «никогда не закроются», чтобы зависимые уходили в `dropped`
по той же ветке, что и «блокеры не закрыты этим прогоном».

### B. SCOPE запрещает читать то, что фазе обязательно надо прочесть

`issue-loop.js`, строки 153-161.

Первая строка: «читай и правь ТОЛЬКО внутри `habit-tracker/`». Дальше: «НИКОГДА, даже
если тикет их называет: `.claude/`, `issues/`, `docs/`, … `graphify-out/`».

`SCOPE_TEXT` подмешан в Preflight, Plan, Implement, Simplify, Standards, Alignment и
Antivibe. При этом:

- Preflight обязан открыть `issues/PHASE-03/backlog/90-….md` и прогнать глоб по `issues/`;
- Alignment отправлен в `docs/PHASE-*/architecture/**`;
- Antivibe отправлен в `~/.claude/skills/antivibe/SKILL.md` и `graphify-out/graph.json`;
- Implement обязан загрузить скилл из `.claude/skills/`.

Формулировка спасается только последней строкой абзаца («**правка** вне
`habit-tracker/` — finding/blocker») и оговоркой про `personal-os` («читать можно,
править нельзя»). Именно эта оговорка и делает остальные пункты списка похожими на
запрет чтения: раз для одного каталога разницу выписали явно, для других её как будто нет.

Риск реальный, но не фатальный: агент, скорее всего, разрулит по смыслу. Дешевле
переписать первую строку в «**правь** ТОЛЬКО внутри `habit-tracker/`» и вынести
read-only исключения отдельным предложением: тикет, `docs/`, ADR, `graphify-out/graph.json`,
скиллы — читать обязательно, писать нельзя.

### C. Номер тикета уникален не везде, и в бэклоге есть номера-призраки

`issue-swarm.js`, `TRIAGE_PROMPT`, строки 106-109: «Номер уникален по всему дереву
`issues/` (CLAUDE.md §5), поэтому файл будет один».

Для номеров 01 и 02 это неверно — у PRD своя нумерация:

```
issues/PHASE-*/*/01-*.md → PHASE-01/done/01-backend-api-key-auth.md
                            PHASE-03/PRDs/01-proverka-posle-pravok.md
issues/PHASE-*/*/02-*.md → PHASE-01/done/02-deploy-vps-tailscale.md
                            PHASE-03/PRDs/02-kontrakt-roya.md
```

Второй файл лежит не в `done/`, поэтому агент запишет блокер в `openBlockers` и выбросит
тикет. Задевает два тикета:

- **#151** — `**Blocked by**: [#108] (…), [#147], [#149], [#02] (деплой VPS + Tailscale)`.
  Блокер `[#02]` настоящий и закрыт (`PHASE-01/done/02-deploy-vps-tailscale.md`),
  но из-за дубля в `PRDs/` прочитается как открытый.
- **#129** — `**Blocked by**: [#127], [#128], [`PHASE-01/done/53-apply-plan-batch-endpoint.md`] — …`.
  Правило «отрежь хвост по первому `—`, `.` или `;`» режет по точке в `.md`, и из остатка
  пути `PHASE-01` вылущивается число `01`. Блокера #01 в тикете нет вообще — это кусок
  имени каталога.

Обе поломки — от того, что номер блокера вынимается регуляркой из строки, где встречаются
и пути, и номера фаз. Дешёвая починка: брать номер только из форм `[#NNN]` и `NNN` через
запятую, а всё, что стоит внутри обратных кавычек или содержит `/`, игнорировать; плюс
искать блокер глобом `issues/PHASE-*/{backlog,in-work,done,rejected,concerns}/N-*.md`,
без `PRDs/`.

---

## Что делать

1. Починить A в `issue-swarm.js` — это единственный дефект, который портит результат
   работы, а не отсев.
2. Переписать первую строку `SCOPE_TEXT` (B) — одно предложение.
3. Уточнить правило разбора `**Blocked by**` и глоб поиска блокера (C), либо просто
   помнить про #129 и #151 и передавать их в `args.issues` руками.
4. Перед первым ночным прогоном на свежей машине перенести `Bash(env *)` из
   `settings.local.json` в `settings.json` — иначе тесты бэкенда встанут на промпте.
5. Запускать первый прогон с `concurrency = 1` и коротким набором из первой волны,
   например `[108, 121, 134]`: у всех трёх нет зависимостей, и все три чисто backend +
   frontend, без `ios/`.
