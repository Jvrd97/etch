# Workflows: issue-loop и issue-swarm

Две петли, которые доводят локальный тикет до состояния «ревью пройдено» без ручного
ре-промпта между шагами. `issue-loop` работает по одному тикету, `issue-swarm` — по набору,
в порядке зависимостей.

## Запуск

Один тикет:

```
Workflow({ name: 'issue-loop',
           args: { issue: 'issues/PHASE-03/backlog/90-day-summary-evaluate-day-and-streak.md',
                   maxRounds: 3 } })
```

Набор тикетов (порядок петля посчитает сама по строке `**Blocked by**`):

```
Workflow({ name: 'issue-swarm',
           args: { issues: ['issues/PHASE-03/backlog/97-inbox-skeleton-clickup-manual-poll.md',
                            'issues/PHASE-03/backlog/98-inbox-sources-and-allowlist-screen.md',
                            'issues/PHASE-03/backlog/99-inbox-worker-and-schedule.md'],
                   maxRounds: 3 } })
```

## Фазы issue-loop

| Фаза | Что делает | Что останавливает петлю |
| --- | --- | --- |
| Preflight | read-only разведка по коду: что тикет просит, что уже есть, где противоречит | вердикт не `proceed` — выход до первого раунда, 0 раундов |
| Plan | read-only: какие файлы, тесты, контракты; расхождение с Module Map Impact | агент вернул null |
| Implement | TDD red → green → refactor, feedback loops по слоям | null-агент |
| Simplify | агент `simplifier` по тронутым файлам, поведение не меняется | ничего (null не останавливает) |
| Review | три агента параллельно: стандарты, вписанность в кодовую базу, antivibe-гейт | все три вернули null; любой вернул `NEEDS_DISCUSSION` |
| Verdict | сводит три ревью в APPROVE / REQUEST CHANGES | аппрув — выход из цикла |
| Report | отчёт для утреннего ревью в `.claude/loop-reports/<id>.{json,md}` | выполняется всегда, даже без аппрува |

Раунд с красными feedback loops ревью пропускает: имплементеру сразу возвращается одна
задача «почини красное». Три ревью-агента на заведомо сломанном коде — сожжённый раунд.

Отклонённый раунд возвращается имплементеру через `changeRequests` — плоский список
атомарных правок с указанием файла. План, findings ревьюеров и preflight в следующий раунд
НЕ передаются: контекст сознательно узкий.

## Что петля НЕ делает

- **Не коммитит.** Оставляет изменения в рабочем дереве.
- **Не двигает тикет по lifecycle** (`backlog → in-work → done`). Папки `in-review` в этом
  проекте нет вовсе.
- **Не запускает graphify.** `graphify update ./src` идёт после коммита, руками (CLAUDE.md §2).
- **Не трогает `habit-tracker/ios/**`.** Сборки Swift в петле нет, проверить нечем: тикет,
  чья основная работа в iOS, Preflight возвращает как `blocked`.
- **Не проходит `human-in-the-loop`-тикеты.** Preflight читает причину из скобок после
  `**Type**` и останавливается на ней.

Всё это делает человек после просмотра вердикта и отчёта.

## args

| arg | Дефолт | Что даёт |
| --- | --- | --- |
| `issue` | — (обязателен для issue-loop) | путь к тикету |
| `issues` | — (обязателен для issue-swarm) | список путей к тикетам |
| `maxRounds` | `3` | сколько раундов до сдачи |
| `model` | — | общий переключатель обеих ролей |
| `implementModel` | `model ?? 'opus'` | модель имплементера и simplify |
| `reviewModel` | `model ?? 'opus'` | модель preflight/plan/ревью/вердикта/report |
| `scopeDir` | `'habit-tracker'` | граница правок; сузить можно, расширять смысла нет |
| `repoRoot` | абсолютный путь репозитория | нужен только флагу `bun --cwd`, которому относительный путь не годится |
| `simplifierAgent` | `'simplifier'` | подменить агент упрощения |
| `setContext` | `''` | внешние факты окружения в блок `/set` |
| `startedAt` | `null` | пробрасывается в отчёт |
| `concurrency` | `1` | (только swarm) сколько петель в волне |
| `loopScript` | абсолютный путь к `issue-loop.js` | (только swarm) какую петлю звать |

Обе модели по умолчанию Opus. Замер сделан на другом проекте (alv, 2026-08-08): Sonnet на
имплементации примерно в полтора раза быстрее, но чаще оставляет красные feedback loops, а
такой раунд сгорает впустую — экономия возвращается лишними раундами.

## Скоуп: почему `habit-tracker/`, а не каталог сервиса

Тикеты здесь вертикальные: у всех 78 тикетов `PHASE-03/backlog` есть раздел
«Vertical Slice Layers», один тикет трогает и backend, и frontend сразу. Делить работу по
сервисам, как это делает исходная петля alv, нечем и незачем.

`habit-tracker/` отсекает ровно то, что надо отсечь: снаружи остаются `issues/`, `docs/`,
`.claude/`, `deploy/`, `bashs/`, `graphify-out/`, корневой `Makefile`, `brain-dumps/` и
соседний репозиторий `personal-os/` — на него тикеты ссылаются как на источник данных для
импорта, читать можно, править нельзя.

**Module Map Impact скоуп не задаёт.** В бэклоге две конвенции путей (часть тикетов пишет
`backend/app/...`, часть — полный `habit-tracker/services/backend/...`), плюс ссылки на
`habit-tracker/mac`, каталога которого ещё нет. Скоуп из такого поля — генератор ложных
блокеров. Он передаётся в Plan и Review как *ожидание*: «тикет обещал эти файлы, дифф
трогает те — объясни расхождение», с нормализацией префикса на входе.

**Следствие для swarm.** Стены между параллельными петлями в общем рабочем дереве нет, и
`concurrency` по умолчанию равен 1: тикеты идут по одному, в порядке `Blocked by`. Ставить
больше единицы можно только когда каждой петле дан свой git worktree.

## Почему docker-обход зашит как факт

Docker-демон на этой машине не поднят: сокета нет, порт 5433 закрыт, 5432 открыт. Штатный
`make check` бэкенда падает не из-за кода, а из-за того, что его цель `test` зависит от
цели `db`, а `db` — это `docker compose up -d postgres` с жёстко прибитым портом 5433.

Поэтому в промптах петли `make check`, `make test` и `make db` агентам запрещены, а тесты
гоняются напрямую по живому Postgres на 5432:

```
uv run --directory habit-tracker/services/backend ruff check app tests
uv run --directory habit-tracker/services/backend ruff format --check app tests
uv run --directory habit-tracker/services/backend mypy --strict app
uv run --directory habit-tracker/services/backend alembic heads
env POSTGRES_HOST=localhost POSTGRES_PORT=5432 TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5432/habit_tracker_test uv run --directory habit-tracker/services/backend pytest tests/ -q
```

```
bun --cwd=<абсолютный путь>/habit-tracker/services/frontend test
bunx tsc -p habit-tracker/services/frontend/tsconfig.json --noEmit
bun --cwd=<абсолютный путь>/habit-tracker/services/frontend run lint
```

Две детали, которые легко сломать при правке:

- форма `env VAR=… uv run …`, а не `VAR=… uv run …`. Вторая не матчится правилом
  `Bash(uv run *)` и вешает сессию на permission-промпте; первая проходит по `Bash(env *)`;
- `alembic heads` обязан напечатать ровно одну строку (CLAUDE.md §3). Две головы — красный
  loop `backend.migrations`, тот же блокер, что упавшие тесты;
- команды идут строго по одной, без `&&`, `;` и пайпов, и без `cd`: составная команда не
  матчится ни одним allow-правилом.

`bun` и `bunx` есть в `settings.local.json`, но не в `settings.json`. Если прогон идёт под
чужим local-конфигом, фронтовые проверки надо разрешить отдельно.

## Отчёты

`Report` пишет два файла в `.claude/loop-reports/`: `<id>.json` (машинный) и `<id>.md`
(для человека утром — что сделано, почему, файлы, ADR, тесты, раунды, чек-лист ревьюера).
Каталог в `.gitignore` не внесён: если отчёты не должны попадать в git, строку
`.claude/loop-reports/` добавляет человек — петля корневой `.gitignore` не трогает.

## Чего в этой версии нет и почему

- **Фаза Archify.** Исходная петля правит `docs/architecture/services/<svc>.archify.json`
  в режиме amend. Здесь archify-артефактов нет ни одного, каталога `docs/architecture/`
  не существует, и amend'ить нечего — включённая как есть, фаза генерировала бы картину
  заново каждый тикет. Роль «держать картину свежей» несёт graphify. Вернуть фазу можно
  после того, как базовый `archify.json` будет сгенерирован отдельной задачей.
- **Скилл night-run и рендер в `docs-html/`.** `night-report.js` читает `.dsh/watcher/`
  (results, timings.tsv, reviews), которые пишет ночной watcher. Ни каталога, ни watcher'а
  здесь нет — рендерер выдал бы страницу с пустыми блоками. Markdown-отчёт фаза Report
  пишет сама.
- **`lib/service-of.js` и таблицы сервисов.** Выводить нечего: юнита два, тикеты плоские
  и вертикальные.
- **Ночной прогон (`bashs/issue-watcher.sh`).** Не переносился. `ralph-once.sh` и
  `ralph-loop.sh` в `.claude/scripts/` ему не замена и сейчас не работают вовсе: они
  сканируют `issues/*.md`, а тикеты лежат в `issues/PHASE-03/backlog/`.

## Соседние файлы

- `.claude/agents/simplifier.md` — агент фазы Simplify, единственный привязанный через
  `agentType`. Один на оба языка: срез вертикальный, Python и TypeScript приезжают вместе.
- `.claude/agents/reviewer.md` — на него ссылается промпт ревью стандартов.
- `.claude/skills/senior-python-backend/SKILL.md` — единственный скилл, который грузит
  имплементер и ревьюер стандартов. Ровно один: два скилла разом рвали ответы по длине.
- `~/.claude/skills/antivibe/SKILL.md` — гейт понятности, скилл глобальный, в репозиторий
  не копируется.
- Hook `.claude/hooks/check-feedback-loops.sh` работает на событие Stop и фильтрует
  `git status` по путям `src|app|lib|services|api` от корня репозитория. Пути этого проекта
  начинаются с `habit-tracker/`, поэтому на работу петли он не срабатывает. Если фильтр
  когда-нибудь расширят, петле нужен `CLAUDE_SKIP_FEEDBACK_CHECK=1` — иначе хук будет
  драться с откатами фазы Simplify.
