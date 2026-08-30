// issue-loop — closed loop preflight → plan → implement → simplify → triple review →
// verdict → report для ОДНОГО тикета habit_tracker_ai.
//
// Что делает: берёт путь к тикету, реализует его через TDD, прогоняет три независимых
// ревью (стандарты кода + вписанность в кодовую базу + antivibe-гейт понятности),
// сводит вердикт. REQUEST_CHANGES — findings уходят обратно имплементеру, до maxRounds
// раундов. Последняя фаза всегда оставляет отчёт для утреннего ревью.
//
// Что НЕ делает: не коммитит, не двигает тикет по lifecycle (backlog → in-work → done),
// не запускает graphify. Это необратимые шаги, их делает человек после просмотра вердикта.
//
// ---------------------------------------------------------------------------------
// Портировано из alv/.claude/workflows/issue-loop.js (версия 2026-08-28). Отличия
// целевого проекта и что из-за них изменено — здесь, а не в комментариях по коду:
//
// 1. СКОУП. В alv тикет живёт внутри backend/services/<svc>-service, и стена между
//    параллельными петлями — каталог сервиса. Здесь тикеты ВЕРТИКАЛЬНЫЕ: у всех 78
//    тикетов PHASE-03/backlog есть раздел «Vertical Slice Layers», один тикет трогает
//    и backend, и frontend сразу. Поэтому deriveService(), KNOWN_SERVICES и
//    ID_PREFIX_TO_SERVICE выброшены целиком: выводить нечего. Скоуп один на все тикеты —
//    habit-tracker/ плюс явный deny-список (SCOPE_TEXT ниже).
//
// 2. MODULE MAP НЕ ЗАДАЁТ СКОУП. В бэклоге две конвенции путей: часть тикетов пишет
//    `backend/app/...` (относительно habit-tracker/services/), часть — полный
//    `habit-tracker/services/backend/...`; плюс ссылки на habit-tracker/mac, каталога
//    которого ещё нет. Скоуп из такого поля — генератор ложных блокеров. Module Map
//    передаётся в Plan и Review как ОЖИДАЕМЫЙ список файлов: «тикет обещал эти, дифф
//    трогает те — расхождение объясни», с нормализацией префикса на входе.
//
// 3. ФАЗА ARCHIFY УБРАНА. Она устроена как amend существующей диаграммы
//    (docs/architecture/services/<svc>.archify.json), а в этом репозитории
//    archify-артефактов нет ни одного и каталога docs/architecture/ не существует.
//    Включённая как есть, она бы каждый тикет генерировала картину заново — дифф
//    диаграммы стал бы шумом. Роль «держать картину архитектуры свежей» здесь несёт
//    graphify (CLAUDE.md §2, живой graphify-out/), и он запускается после коммита,
//    а не внутри петли. Вернуть фазу можно после того, как базовый archify.json будет
//    сгенерирован отдельной задачей.
//
// 4. ФАЗА REPORT СОХРАНЕНА, НО БЕЗ night-run. В alv она вызывает
//    .claude/skills/night-run/scripts/night-report.js, который читает .dsh/watcher/
//    (results, timings.tsv, reviews) и рендерит в docs-html/night-run/. Ни одного из
//    этих каталогов здесь нет, а пишет их ночной watcher, которого тоже нет — рендерер
//    выдал бы страницу с пустыми блоками. Поэтому Report пишет два файла сам:
//    машинный JSON и человеческий .md для утреннего ревью, в .claude/loop-reports/.
//
// 5. FEEDBACK LOOPS РАЗДЕЛЕНЫ ПО СЛОЯМ. На вертикальном тикете один общий «зелёный
//    lint» не значит ничего: непонятно, чей. backend {lint, types, migrations, tests}
//    и frontend {lint, types, tests} — раздельно; нетронутый слой = n/a.
//
// 6. DOCKER-ДЕМОН НА ЭТОЙ МАШИНЕ НЕ РАБОТАЕТ — это факт окружения, а не исключение.
//    Штатный `make check` бэкенда падает, потому что его цель test зависит от цели db,
//    а db — это `docker compose up -d postgres` с жёстко прибитым портом 5433. Порт
//    5433 закрыт, 5432 открыт. Поэтому тесты гоняются обходом с явными переменными
//    (BACKEND_CHECKS ниже), а make check / make test / make db агентам запрещены.
//
// 7. ID ТИКЕТА. Регулярка alv требовала буквенный сегмент перед числом (auth-22-...).
//    Здесь имена начинаются с числа (89-import-personal-os-...), поэтому регулярка
//    расширена: буквенный префикс стал необязательным.
//
// Запуск:
//   Workflow({ name: 'issue-loop',
//              args: { issue: 'issues/PHASE-03/backlog/90-day-summary-evaluate-day-and-streak.md',
//                      maxRounds: 3 } })

export const meta = {
  name: 'issue-loop',
  description: 'Closed loop: implement one vertical issue via TDD, triple-review incl. antivibe gate, iterate until approved',
  whenToUse: 'Автономно довести один AFK-тикет с готовыми acceptance до состояния «ревью пройдено», без ручного ре-промпта между шагами.',
  phases: [
    { title: 'Preflight', detail: 'read-only: тикет ещё актуален? что из него уже есть в коде' },
    { title: 'Plan', detail: 'read-only: какие файлы среза, контракты, тесты' },
    { title: 'Implement', detail: 'TDD red→green→refactor + feedback loops по слоям' },
    { title: 'Simplify', detail: 'агент simplifier по тронутым файлам, поведение не меняется' },
    { title: 'Review', detail: 'standards + codebase-alignment + antivibe gate, параллельно' },
    { title: 'Verdict', detail: 'свести три ревью в APPROVE / REQUEST CHANGES' },
    { title: 'Report', detail: 'отчёт для утреннего ревью: что/почему/файлы/ADR/чек-лист → .claude/loop-reports/' },
  ],
}

// args may arrive JSON-encoded as a plain string depending on the caller — normalize.
const _args = typeof args === 'string' ? JSON.parse(args) : args
const issuePath = _args?.issue
const maxRounds = _args?.maxRounds ?? 3
if (!issuePath) throw new Error('args.issue (path to issue .md) is required')

// Обе роли на Opus. Замер сделан на alv 2026-08-08 (другой проект, но та же петля):
// Sonnet на имплементации примерно в полтора раза быстрее на агента, но чаще оставляет
// красные feedback loops, а раунд с красными loops пропускает ревью и сгорает впустую —
// экономия на токенах возвращается лишними раундами. Роли раздельные: переключить одну
// имплементацию можно через args.implementModel, не трогая ревью.
const implementModel = _args?.implementModel ?? _args?.model ?? 'opus'
const reviewModel = _args?.reviewModel ?? _args?.model ?? 'opus'

// В рантайме Workflow нет ни process, ни import — вычислить корень репозитория нечем,
// поэтому он вшит и переопределяется args.repoRoot. Нужен ровно для одного: у флага
// bun --cwd абсолютный путь обязателен.
const REPO_ROOT = _args?.repoRoot ?? '/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai'

// --- scope ---------------------------------------------------------------------
// Один скоуп на все тикеты: сервисной стены здесь нет (см. п.1 шапки). habit-tracker/
// отсекает ровно то, что надо отсечь: issues/, docs/, .claude/, deploy/, bashs/,
// graphify-out/, brain-dumps/, корневой Makefile и соседний репозиторий personal-os/,
// на который тикеты ссылаются как на источник данных, а не как на код для правки.
const scopeDir = _args?.scopeDir ?? 'habit-tracker'

const BACKEND_DIR = 'habit-tracker/services/backend'
const FRONTEND_DIR = 'habit-tracker/services/frontend'

// Проверки бэкенда. Каждая строка — отдельный Bash-вызов.
// Про env-префикс: `POSTGRES_HOST=... uv run ...` не матчится правилом Bash(uv run *)
// и вешает сессию на permission-промпте; форма `env VAR=... uv run ...` матчится
// правилом Bash(env *), которое в allow-списке есть. Менять форму осторожно.
const BACKEND_CHECKS = [
  `uv run --directory ${BACKEND_DIR} ruff check app tests`,
  `uv run --directory ${BACKEND_DIR} ruff format --check app tests`,
  `uv run --directory ${BACKEND_DIR} mypy --strict app`,
  `uv run --directory ${BACKEND_DIR} alembic heads`,
  `env POSTGRES_HOST=localhost POSTGRES_PORT=5432 TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5432/habit_tracker_test uv run --directory ${BACKEND_DIR} pytest tests/ -q`,
]

const FRONTEND_CHECKS = [
  `bun --cwd=${REPO_ROOT}/${FRONTEND_DIR} test`,
  `bunx tsc -p ${FRONTEND_DIR}/tsconfig.json --noEmit`,
  `bun --cwd=${REPO_ROOT}/${FRONTEND_DIR} run lint`,
]

const CHECKS_TEXT = `ПРОВЕРКИ. Гоняешь ветку того слоя, который реально тронул диффом; нетронутый слой = n/a.
Каждая команда — ОТДЕЛЬНЫЙ Bash-вызов, без '&&', без ';', без пайпов.

Бэкенд (habit-tracker/services/backend):
${BACKEND_CHECKS.map((c) => `  ${c}`).join('\n')}
  alembic heads обязан напечатать РОВНО ОДНУ строку (CLAUDE.md §3). Две головы — это
  красный migrations, тот же блокер, что упавшие тесты, а не мелочь.

Фронт (habit-tracker/services/frontend):
${FRONTEND_CHECKS.map((c) => `  ${c}`).join('\n')}

DOCKER НА ЭТОЙ МАШИНЕ НЕ РАБОТАЕТ — демон не поднят, порт 5433 закрыт, 5432 открыт.
Поэтому: НЕ вызывай make check, make test, make db, docker compose up. Штатный make check
падает не из-за твоего кода, а из-за цели db (docker compose up -d postgres на 5433).
Тесты бэкенда гоняются только командой с env-префиксом выше — она ходит в живой
Postgres на 5432. Это постоянное правило окружения, а не разовый обход.

iOS (habit-tracker/ios/**) петля не проверяет: сборки Swift в петле нет. Тикет, основная
работа которого в ios/, веди не здесь — это finding для человека.`

// Параллельные петли (если каллер дал каждой свой worktree) делят пути, поэтому дифф
// всегда берём с путём — чужая работа в ревью попадать не должна.
const DIFF_CMD = `git --no-pager diff -- ${scopeDir}`
const DIFF_STAT_CMD = `git --no-pager diff --stat -- ${scopeDir}`
const UNTRACKED_CMD = `git status --porcelain -- ${scopeDir}`

const SCOPE_TEXT = `SCOPE (жёстко): ПРАВЬ только внутри ${scopeDir}/.
Тикеты здесь вертикальные — один тикет законно трогает и backend, и frontend сразу,
делить работу по сервисам не надо.

ЧИТАТЬ обязан и за пределами ${scopeDir}/: свой тикет в issues/, ADR и документы
в docs/, скиллы в .claude/skills/, граф graphify-out/graph.json, соседний репозиторий
personal-os/ как источник данных для импорта. Чтение не ограничено ничем — ограничена
запись.

ПИСАТЬ вне ${scopeDir}/ нельзя НИКОГДА, даже если тикет прямо называет путь:
.claude/, issues/, docs/, bashs/, deploy/, .github/, .gitignore, graphify-out/,
brain-dumps/, корневой Makefile, *.env, personal-os/. Оркестрация, скиллы и тикеты
не часть работы по тикету никогда. Правка вне ${scopeDir}/ — finding/blocker,
не действие.

MODULE MAP — ОЖИДАНИЕ, НЕ ГРАНИЦА. Раздел «Module Map Impact» тикета (поля **New**,
**Modified**) говорит, какие файлы тикет собирался тронуть. Он ненадёжен как граница:
в бэклоге две конвенции путей. Нормализуй на входе — путь, начинающийся с backend/ или
frontend/, читай как habit-tracker/services/<то же>. Расхождение «обещали эти, тронули
те» — это то, что надо ОБЪЯСНИТЬ, а не автоматический блокер. Путь на habit-tracker/mac —
каталога ещё нет, работа туда не идёт.

${CHECKS_TEXT}`

// Формат тикета отличается от alv: YAML-frontmatter нет ни в одном файле, статус
// задаётся lifecycle-папкой. Описание формата едет в каждую read-фазу, чтобы агент
// не искал поля, которых нет.
const TICKET_FORMAT = `ФОРМАТ ТИКЕТА (frontmatter НЕТ — не ищи его):
- первая строка: '# <заголовок>' — id тикета в заголовке не повторяется, он в имени файла;
- '**Type**: AFK' либо '**Type**: human-in-the-loop (<причина в скобках>)'. Причина в
  скобках — это то, чего агент сделать не может (согласие в браузере, доступ, решение);
- '**Blocked by**: 108 (пояснение), 99' — сначала список номеров, дальше свободная проза.
  Номера бери только до первого '—', '.' или ';': в прозе живут ADR-0017, #155 и номера портов;
- '**Estimated**: M (~6 агент-часов)' — значащая только первая буква S|M|L;
- 'ADR: \`docs/PHASE-03/ADRs/<lifecycle>/ADR-00NN-....md\` (Р2, Р8)' — строка первого
  уровня без '**'. Путь к ADR и ссылки на конкретные решения внутри него уже выписаны:
  грепать ADR по docs/ не надо, читай названный файл;
- разделы: '## Vertical Slice Layers', '## Module Map Impact' (именно Impact — не
  'Module Map', как в других проектах), '## Acceptance', '## Out of Scope';
- статус тикета — это ИМЯ ПАПКИ (backlog / in-work / done / rejected / concerns / PRDs),
  поля status: в теле нет. Папки in-review здесь не существует.
Номер тикета уникален по всему дереву issues/ (CLAUDE.md §5): блокер N ищется глобом
issues/PHASE-*/*/N-*.md, и его папка и есть его статус.`

// --- /set: сборка окружения в каждого агента -----------------------------------
// Агенты Workflow не проходят через инструмент Agent, поэтому PreToolUse-хук
// ~/.claude/hooks/set/inject-subagent.py до них не достаёт — блок подмешиваем здесь сами.
// Факты окружения приходят снаружи через args.setContext (ночной прогон); при ручном
// запуске днём их нет — остаётся то, что петля знает про себя сама.
const SET_CONTEXT = typeof _args?.setContext === 'string' ? _args.setContext.trim() : ''
const SET_BLOCK = `## Сборка окружения (скилл /set)

Задача петли: довести до готовности РОВНО ОДИН тикет ${issuePath}.
Тикет вертикальный: один срез через схему, сервис, API и UI — не «задача бэкенда».
Маршрут: issue-loop — preflight → план → TDD-имплементация → упрощение → три ревью → вердикт → отчёт.
Ты ведёшь ОДНУ фазу маршрута, не всю работу: делаешь свою фазу и возвращаешь результат структурой.
${SET_CONTEXT}`.trim()

// Единственная точка запуска агента в этом файле: блок сборки получает каждый, без
// исключений. Прямой вызов agent() мимо runAgent — регресс, агент останется слепым.
const runAgent = (prompt, opts) => agent(`${SET_BLOCK}\n\n---\n\n${prompt}`, opts)


// Роль упростителя, вшитая из .claude/agents/simplifier.md — файл остаётся источником
// правды, но петля больше не зависит от реестра custom-агентов.
const SIMPLIFIER_ROLE = `You simplify code that was written moments ago for one ticket in \`habit_tracker_ai\`. Your
job is to make the code easier for a tired reader, not shorter and not cleverer. Behaviour,
public signatures, HTTP contracts, event names and tests stay exactly as they are.

Tickets here are **vertical**: one ticket normally touches both layers, so you work in both.

- Backend — \`habit-tracker/services/backend\`: FastAPI, SQLAlchemy 2.0 (\`Mapped[]\`/
  \`mapped_column()\`), Pydantic v2, Alembic, uv, pytest. Layers: \`app/models\`, \`app/crud\`,
  \`app/schemas\`, \`app/api\`, \`app/core\`. There is no \`app/services/\` — do not invent one.
- Frontend — \`habit-tracker/services/frontend\`: Next.js 16, React 19, Tailwind 4, bun,
  \`bun test\`. Shared code lives in \`lib/\`, \`components/\`, \`hooks/\`.

## Boundaries

- Touch only the files you were given (\`filesTouched\`). Never edit anything outside
  \`habit-tracker/\`, and never \`.claude/\`, \`issues/\`, \`docs/\`, \`deploy/\`, \`bashs/\`,
  \`graphify-out/\`, the root \`Makefile\`, or the neighbouring \`personal-os/\` repository.
- Never touch \`habit-tracker/ios/**\`: there is no Swift build in this loop, so you cannot
  prove your edit is safe.
- Never change: test assertions, migration files, public function/endpoint signatures,
  Pydantic field names, event names, log keys, React component props that other files pass,
  review markers (\`# [review:need-review] …\`, \`// [review:need-review] …\`).
- Never add: a new module, class, base class, Protocol, decorator, hook, config setting, or
  parameter. Simplification only removes or flattens.
- No \`# type: ignore\`, no \`// @ts-ignore\`, no \`# noqa\`, no eslint-disable to make a check pass.

## What to remove or flatten (in this order)

1. **Abstraction with one caller** — a helper, class, factory, custom hook or layer used
   from exactly one place: inline it, unless inlining makes the caller longer than ~25 lines.
2. **Speculative surface** — parameters with a default that no caller overrides, flags for a
   case the ticket does not name, \`**kwargs\` / rest props passed nowhere, unreachable branches.
3. **Duplicates of code that already exists** — your own retry, date/day-boundary arithmetic,
   logging, error classes, settings parsing, fetch wrapper or formatting helper when
   \`app/core/**\` (backend) or \`lib/**\`, \`hooks/**\`, \`components/**\` (frontend) already
   provide it. Grep before you decide; replace with the import, do not re-implement.
   The day boundary in particular must be computed one way across the whole slice.
4. **Nesting** — early returns instead of \`if/else\` pyramids; no nested ternaries; one
   \`try\` per failure you actually handle, never a blanket \`except Exception\` / \`catch (e) {}\`.
5. **Noise** — comments restating the code, dead imports, unused constants, \`Optional[X]\`
   → \`X | None\`, \`List[X]\` → \`list[X]\`, \`typing.Dict\` → \`dict\`; on the frontend, boolean
   flag pairs that should be one discriminated union (CLAUDE.md §3) — but only when the
   union already exists, otherwise it is a new abstraction and rule "never add" wins.
6. **Names** — a variable named after its type or its history (\`data2\`, \`newResult\`) gets a
   name after its meaning, but only inside the files you own.

Leave alone: code that is merely not how you would write it. The models → crud → schemas →
api split on the backend and the app/components/lib split on the frontend are project
convention, not abstractions to collapse. Docstrings on public functions stay.

## Procedure

1. Read every file in \`filesTouched\`; read \`git --no-pager diff -- habit-tracker\` to see
   exactly what the ticket changed. Simplify the ticket's changes first; pre-existing code
   only when it sits in the same function and the fix is mechanical (rule 5).
2. Apply edits. Keep each edit small; do not reformat untouched regions.
3. Run the checks for the layers you actually touched, as separate Bash commands
   (no \`&&\`, no \`;\`, no pipes; do not \`cd\`).

   Backend:
   - \`uv run --directory habit-tracker/services/backend ruff check app tests\`
   - \`uv run --directory habit-tracker/services/backend ruff format --check app tests\`
   - \`uv run --directory habit-tracker/services/backend mypy --strict app\`
   - \`uv run --directory habit-tracker/services/backend alembic heads\` (exactly one line)
   - \`env POSTGRES_HOST=localhost POSTGRES_PORT=5432 TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5432/habit_tracker_test uv run --directory habit-tracker/services/backend pytest tests/ -q\`

   Frontend:
   - \`bun --cwd=/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/habit-tracker/services/frontend test\`
   - \`bunx tsc -p habit-tracker/services/frontend/tsconfig.json --noEmit\`
   - \`bun --cwd=/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/habit-tracker/services/frontend run lint\`

   **The docker daemon on this machine is not running**, so \`make check\`, \`make test\` and
   \`make db\` fail on the \`db\` target (\`docker compose up -d postgres\`, port 5433) regardless
   of your edits. Never call them. The pytest command above talks to the live Postgres on
   5432 — that is the normal way to run backend tests here, not a workaround for today.
   The \`env VAR=… uv run …\` form is deliberate: \`VAR=… uv run …\` does not match the
   permission allow-list and hangs the session on a prompt.
4. Any check red → revert **your** edits with \`git checkout -- <file>\` for each file you
   changed (only that form; never \`git checkout .\`, never \`git stash\`) and report
   \`checks: reverted\`. Do not try to fix the red result — that is the implementer's round.
5. Nothing worth simplifying → change nothing, report \`changed: false\`.

## Report

Return only:

\`\`\`json
{"changed": true|false, "filesTouched": ["..."], "checks": "pass|fail|reverted", "summary": "one or two sentences: what was removed/flattened and why it is safe"}
\`\`\`

No diff, no narrative.`

// --- schemas -----------------------------------------------------------------

const LOOP_STATE = { type: 'string', enum: ['pass', 'fail', 'n/a'] }

const IMPLEMENT_SCHEMA = {
  type: 'object',
  required: ['summary', 'filesTouched', 'feedbackLoops', 'acceptanceCovered'],
  properties: {
    summary: { type: 'string', description: 'Что сделано, 1-3 предложения' },
    filesTouched: { type: 'array', items: { type: 'string' } },
    // Раздельно по слоям: на вертикальном тикете общий «зелёный lint» не значит ничего.
    feedbackLoops: {
      type: 'object',
      required: ['backend', 'frontend'],
      properties: {
        backend: {
          type: 'object',
          required: ['lint', 'types', 'migrations', 'tests'],
          properties: {
            lint: LOOP_STATE,
            types: LOOP_STATE,
            migrations: { ...LOOP_STATE, description: 'alembic heads — ровно одна голова' },
            tests: LOOP_STATE,
          },
        },
        frontend: {
          type: 'object',
          required: ['lint', 'types', 'tests'],
          properties: { lint: LOOP_STATE, types: LOOP_STATE, tests: LOOP_STATE },
        },
      },
    },
    acceptanceCovered: { type: 'boolean', description: 'Все acceptance criteria закрыты?' },
    notes: { type: 'string' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'blockers', 'warnings'],
  properties: {
    verdict: { type: 'string', enum: ['APPROVE', 'REQUEST_CHANGES', 'NEEDS_DISCUSSION'] },
    blockers: {
      type: 'array',
      items: {
        type: 'object',
        required: ['where', 'what', 'fix'],
        properties: {
          where: { type: 'string' }, what: { type: 'string' }, fix: { type: 'string' },
        },
      },
    },
    warnings: { type: 'array', items: { type: 'string' } },
  },
}

// Поля ticket* — разобранная шапка тикета: петля сама читать файлы не умеет, а Plan и
// Report их спрашивают. Разбирает тот, кто и так открывает тикет первым.
const PREFLIGHT_SCHEMA = {
  type: 'object',
  required: ['verdict', 'findings', 'summary'],
  properties: {
    verdict: { type: 'string', enum: ['proceed', 'already-done', 'blocked'] },
    findings: { type: 'array', items: { type: 'string' }, description: 'факты с file:line' },
    summary: { type: 'string' },
    nextAction: { type: 'string' },
    ticketTitle: { type: 'string' },
    ticketType: { type: 'string', description: 'AFK | human-in-the-loop | quick-win' },
    typeReason: { type: 'string', description: 'текст в скобках после human-in-the-loop' },
    blockedBy: { type: 'array', items: { type: 'string' }, description: 'номера блокеров и их lifecycle-папка' },
    adr: { type: 'string', description: 'строка ADR: из тикета целиком, если есть' },
    layers: {
      type: 'array',
      items: { type: 'string', enum: ['backend', 'frontend', 'ios', 'other'] },
      description: 'слои среза, которых тикет реально касается',
    },
  },
}

const PLAN_SCHEMA = {
  type: 'object',
  required: ['summary', 'files', 'tests', 'outOfScope'],
  properties: {
    summary: { type: 'string', description: 'как строим изменение, 2-5 предложений' },
    files: { type: 'array', items: { type: 'string' }, description: 'пути внутри scope, которые тронем' },
    tests: { type: 'array', items: { type: 'string' }, description: 'какие тесты докажут acceptance' },
    contracts: { type: 'array', items: { type: 'string' }, description: 'границы/контракты, которые нельзя нарушить' },
    outOfScope: { type: 'array', items: { type: 'string' } },
    moduleMapDelta: {
      type: 'array', items: { type: 'string' },
      description: 'чем план расходится с Module Map Impact тикета и почему',
    },
  },
}

const SIMPLIFY_SCHEMA = {
  type: 'object',
  required: ['changed', 'filesTouched', 'checks'],
  properties: {
    changed: { type: 'boolean' },
    filesTouched: { type: 'array', items: { type: 'string' } },
    checks: { type: 'string', enum: ['pass', 'fail', 'reverted'] },
    summary: { type: 'string' },
  },
}

const REPORT_SCHEMA = {
  type: 'object',
  required: ['reportPath', 'renderedPath', 'checklistCount'],
  properties: {
    reportPath: { type: 'string', description: '.claude/loop-reports/<id>.json' },
    renderedPath: { type: 'string', description: '.claude/loop-reports/<id>.md' },
    checklistCount: { type: 'integer' },
    note: { type: 'string' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['approved', 'reason', 'changeRequests'],
  properties: {
    approved: { type: 'boolean' },
    reason: { type: 'string' },
    changeRequests: {
      type: 'array',
      description: 'Конкретные правки для следующего раунда имплементации',
      items: { type: 'string' },
    },
  },
}

// --- prompts -----------------------------------------------------------------

const ENV_RULES = `ЖЁСТКОЕ ПРАВИЛО ОКРУЖЕНИЯ (иначе зависнешь навсегда на permission-промпте):
- Bash-команды выполняй СТРОГО ПО ОДНОЙ, без '&&', без ';', без пайпов.
- Работай в текущем рабочем каталоге: НЕ меняй cwd через cd, НЕ создавай git worktree,
  НЕ трогай чужие .claude/worktrees/*. Для подкаталогов — флаги:
  'uv run --directory <dir> ...', 'git -C <dir> ...', 'bunx tsc -p <path>', 'bun --cwd=<abs> ...'.
НЕ коммить. НЕ двигай тикет по папкам. НЕ запускай graphify.`

const PREFLIGHT_PROMPT = `Preflight-разведка тикета ${issuePath}. ТОЛЬКО ЧТЕНИЕ: ничего не менять.
${SCOPE_TEXT}
${ENV_RULES}

${TICKET_FORMAT}

Выясни по РЕАЛЬНОМУ коду, а не по тексту тикета: что тикет просит, что из этого уже есть,
где тикет противоречит текущему коду или именам. Каждый finding — с file:line.

Вердикты:
- "proceed" — реальная работа осталась и она вся внутри SCOPE;
- "already-done" — код уже закрывает acceptance;
- "blocked" — как написано, сделать нельзя. Сюда же два случая, которых в этом
  репозитории больше, чем один: **Type**: human-in-the-loop (тогда причину из скобок
  положи в typeReason и в nextAction — петля дальше не пойдёт) и тикет, чья основная
  работа лежит в habit-tracker/ios/** (Swift петля не проверяет).

Заполни разобранную шапку: ticketTitle, ticketType, typeReason, blockedBy (номер плюс
lifecycle-папка, найденная глобом issues/PHASE-*/*/N-*.md), adr, layers.`

const PLAN_PROMPT = (preflight) => `Фаза плана для тикета ${issuePath}. ТОЛЬКО ЧТЕНИЕ: ничего не менять.
Код пишет следующая фаза; здесь решаем КАК.
${SCOPE_TEXT}
${ENV_RULES}

${TICKET_FORMAT}

Определи: какие файлы тронем; какие тесты докажут acceptance; что остаётся вне скоупа.
Срез вертикальный — план обязан пройти все слои, которые тикет называет в «Vertical Slice
Layers», а не остановиться на бэкенде.

Границы и контракты, которые держим (CLAUDE.md §3 и §4 — они уже в контексте):
- имена событий '<owner>.<entity>.<action>' — имя начинается с сервиса-владельца;
- DTO/Pydantic в ответах API, domain models наружу не отдаём;
- user-specific данные → PostgreSQL/Redis, shared knowledge → векторное хранилище;
- вызовы LLM только через orchestration layer, не из бизнес-кода;
- alembic: ровно одна голова, применённую миграцию не редактируем — пишем новую;
- миграция обратима (есть downgrade).

Отдельным полем moduleMapDelta выпиши, чем план расходится с «Module Map Impact» тикета
и почему: расхождение допустимо и объясняется, молчаливое расхождение — нет.

Самое узкое изменение, вписанное в существующую структуру. Из двух рабочих решений —
то, что быстрее поймёт уставший читатель.
Preflight: ${JSON.stringify(preflight)}`

const SIMPLIFY_PROMPT = (impl) => `Упрости код, только что написанный для тикета ${issuePath}.
${SCOPE_TEXT}
${ENV_RULES}

Трогай ТОЛЬКО эти файлы: ${JSON.stringify(impl.filesTouched)}.
Цель — ясность и единообразие с соседним кодом: лишние слои, дублирование, мёртвые ветки,
избыточные параметры, сложные условия. Поведение, публичные сигнатуры и тесты НЕ менять;
новых абстракций не вводить; review-маркеры [review:need-review] сохранить.
Если упрощать нечего — ничего не трогай, changed=false.
После правок прогони проверки тех слоёв, файлы которых ты тронул. Красное — откати СВОИ
правки (git checkout -- <file> по каждому файлу; никогда git checkout . и никогда git stash)
и верни checks=reverted.`

const REPORT_PROMPT = (ctx) => `Фаза отчёта для тикета ${issuePath}. Работа по тикету закончена
(approved=${ctx.approved}); ты пишешь отчёт для человека, который утром будет ревьюить дифф.
Код не менять.
${ENV_RULES}

Прочитай: тело тикета; текущий дифф ${DIFF_CMD} и новые файлы ${UNTRACKED_CMD}; историю раундов ниже.
ADR искать грепом не надо: строка 'ADR:' в тикете уже даёт путь к файлу и ссылки на
конкретные решения внутри него. Прочитай названный файл и возьми оттуда, что применено.
Если строки ADR в тикете нет — оставь adrs пустым, это законно.

Каталог .claude/loop-reports/ создай, если его нет.

ШАГ 1. Запиши JSON в ${ctx.reportPath} строго такой формы:
{
 "id": "${ctx.id}", "date": "<YYYY-MM-DD сегодня, по date +%F>",
 "layers": ${JSON.stringify(ctx.layers)},
 "title": "<заголовок тикета>", "issuePath": "${issuePath}",
 "verdict": "${ctx.approved ? 'approved' : 'not-approved'}",
 "summary": "<что сделано, 3-6 предложений человеческим языком: какое поведение появилось>",
 "why": "<почему именно так: ключевые решения и отвергнутые альтернативы, 2-4 предложения>",
 "mermaid": "<flowchart LR: компоненты, которых коснулось изменение, и поток данных между ними; 4-12 узлов; без стилей>",
 "files": [{"path": "<относительный путь>", "lines": "<N или N-M, где главное изменение>", "why": "<зачем тронут>"}],
 "adrs": [{"id": "ADR-00NN", "why": "<какое решение оттуда применено>"}],
 "tests": [{"name": "<тест или группа>", "status": "pass|fail"}],
 "rounds": [{"round": 1, "standards": "APPROVE|REQUEST_CHANGES|—", "alignment": "...", "antivibe": "...", "verdict": "approved|changes|—", "note": "<главный блокер раунда одной строкой>"}],
 "errors": [{"phase": "<фаза>", "message": "<что пошло не так: красные loops, null-агенты, NEEDS_DISCUSSION, откаты simplify>"}],
 "checklist": [{"text": "<что ревьюер должен проверить глазами>", "kind": "acceptance|risk|contract|test"}],
 "startedAt": ${JSON.stringify(_args?.startedAt ?? null)}, "generatedAt": "<date -u +%FT%TZ>"
}
Чек-лист: 5-12 пунктов. Сначала acceptance-критерии тикета дословно (kind=acceptance), затем
риски именно этого диффа (kind=risk: миграция и её обратимость, вторая alembic-голова,
идемпотентность, обратная совместимость API, PII в логах, граница суток), затронутые
контракты и имена событий (kind=contract), что доказывают тесты (kind=test). Пункты —
проверяемые утверждения, не вопросы.

ШАГ 2. Запиши рядом человекочитаемый ${ctx.renderedPath} — тот же материал в Markdown,
по-русски, в этом порядке: H1 с id и заголовком тикета; строка вердикта и слоёв; «Что
сделано»; «Почему так»; блок \`\`\`mermaid с диаграммой; таблица файлов (путь | строки |
зачем); ADR; тесты; таблица раундов; ошибки, если были; чек-лист ревьюера
чекбоксами '- [ ] '. Никакого HTML и никаких эмодзи (CLAUDE.md §8).
Отдельного рендерера здесь нет намеренно — night-run из alv читает артефакты ночного
watcher'а, которых в этом репозитории не существует.

Верни reportPath, renderedPath и checklistCount. Файл записать не удалось — верни пустую
строку в соответствующем поле и причину в note.

История раундов: ${JSON.stringify(ctx.history).slice(0, 20000)}
Preflight: ${JSON.stringify(ctx.preflight).slice(0, 4000)}
Тело тикета читай из файла.`

function implementPrompt(round, changeRequests, plan) {
  if (round === 1) {
    return `Apply the implement-issue skill (.claude/skills/implement-issue.md) to this issue: ${issuePath}

${SCOPE_TEXT}

ПЛАН (handoff из фазы plan — следуй ему, не расширяй):
${JSON.stringify(plan, null, 2)}

СНАЧАЛА ЗАГРУЗИ СКИЛЛ, ПОТОМ ПИШИ КОД. Для работы по habit-tracker/services/backend/**
вызови Skill \`senior-python-backend\` — там и подход (models first), и простота, и правила
OOP. Это рамка, в которой пишется тикет, а не справочник «если забыл».
Ровно ОДИН скилл: грузить два разом раздувало контекст настолько, что ответы обрывались
на середине и агент умирал. Конкретику проекта (uv, mypy --strict, SQLAlchemy 2.0,
Alembic, одна голова) бери из CLAUDE.md §3, он уже в контексте.
Для фронта (habit-tracker/services/frontend/**) отдельного скилла в этом репозитории нет:
стандарты — CLAUDE.md §3 (strict, no any, discriminated unions вместо boolean-флагов) и
соседние файлы. Next.js 16 / React 19 / Tailwind 4 / bun — версии смотри в package.json,
а не по памяти.

НЕ разведывай каталоги: никаких \`ls\` по .claude/ или \`ls -R\` по issues/ — скилл
вызывается по имени, тикет открывается по данному пути. Рекурсивные листинги больших
деревьев — верный способ подвесить сессию.

${ENV_RULES}

Строгий TDD: red → green → refactor, по одному acceptance criterion за цикл. Срез
вертикальный: закрывай criterion целиком по слоям, а не «сначала весь бэкенд, потом
весь фронт». После закрытия всех criteria прогони feedback loops тех слоёв, которые тронул.
Красное — чини, не завершай.

ПРОСТОТА — ТРЕБОВАНИЕ, НЕ ПОЖЕЛАНИЕ. Пиши самое скучное решение, которое закрывает
acceptance тикета, и на этом останавливайся.
- Не строй абстракцию под один вызывающий: слой, фабрика, реестр, базовый класс и
  протокол оправданы вторым потребителем, не первым.
- Не добавляй ничего «на будущее»: параметры, флаги, хуки, обобщения, ветки под случай,
  которого в тикете нет. Чего нет в acceptance — того не пишем.
- Не заводи новый модуль/таблицу/событие, если задача решается в существующем.
  Сначала ищи готовое в кодовой базе и переиспользуй.
- Конфиг заводи только там, где значение реально должно меняться снаружи; иначе
  именованная константа рядом с кодом.
- Меньше кода при равном поведении — всегда лучший вариант. Если решение выглядит
  умным, оно, скорее всего, неправильное.

Review tracking (CLAUDE.md §9): в каждый тронутый файл кода добавь header
[review:need-review] <номер тикета> + summary-строку. Лидер комментария по языку:
'#' для Python/SQL/YAML/bash, '//' для TypeScript/Swift. В .md, .json и миграции без
логики маркер не ставим.

НЕ коммить. НЕ двигай тикет по папкам. Только реализуй и оставь рабочее дерево с
изменениями. Верни структурированный результат: feedbackLoops заполняй по обоим слоям,
нетронутый слой целиком n/a.`
  }
  return `Раунд ${round}. Предыдущая имплементация тикета ${issuePath} завернута на ревью.
${SCOPE_TEXT}
Bash-команды строго по одной (без '&&'/';'/пайпов), cwd не менять, worktree не создавать.
Внеси РОВНО эти правки, ничего сверх:

${changeRequests.map((c, i) => `${i + 1}. ${c}`).join('\n')}

Правки вноси минимальные — ровно то, что закрывает замечание. Раунд правок это не повод
для рефакторинга, новой абстракции или обобщения «раз уж полез». Меньше кода при равном
поведении — лучший вариант.

После правок снова прогони feedback loops тронутых слоёв. TDD: если меняешь поведение —
сначала тест. НЕ коммить, НЕ двигай тикет. Верни структурированный результат.`
}

const STANDARDS_PROMPT = `Ты reviewer (.claude/agents/reviewer.md). Отревью текущие изменения
рабочего дерева против стандартов проекта.
${SCOPE_TEXT}
Файл, который тикет создал/изменил вне SCOPE, — BLOCKER сам по себе.

0. Для Python загрузи ОДИН скилл — \`senior-python-backend\` (Skill tool) — и ревьюй против
   него, а не по памяти. Второй скилл не грузи: два разом рвут ответы по длине. Для
   TypeScript отдельного скилла нет — стандарты берёшь из CLAUDE.md §3 и соседних файлов.
1. Возьми дифф: \`${DIFF_CMD}\` + \`${DIFF_STAT_CMD}\` + новые файлы через \`${UNTRACKED_CMD}\`.
   Изменения вне этого пути — чужая работа, их не ревьюй и не упоминай.
2. Прочитай тикет ${issuePath} — пойми intent и acceptance.
3. Проверь каждый файл против стандартов (типы везде, mypy --strict, no any, no silent
   except, no debug print, no magic numbers, TDD-тесты осмысленные, DTO в ответах API,
   миграция обратима и не редактирует применённую, никаких PII в логах).
4. Прогони feedback loops тронутых слоёв и отметь их статус. alembic heads с двумя
   головами — блокер, а не предупреждение.

5. Отдельно проверь ПРОСТОТУ. Переусложнение — такой же дефект, как баг, и заворачивается
   так же:
   - абстракция под одного потребителя (слой, фабрика, реестр, базовый класс, протокол) —
     блокер, если второго вызывающего в диффе нет;
   - код под случай, которого нет в acceptance (флаг, параметр, ветка «на будущее») —
     блокер: это непроверяемое поведение в проде;
   - новый модуль/таблица/событие там, где хватало существующего, — блокер;
   - конфиг-значение, которое никто не меняет снаружи, — должно быть константой.
   Формулируй такие замечания как «убрать X, оставить Y», с конкретным файлом.

Верни структуру: verdict (APPROVE если 0 блокеров; REQUEST_CHANGES если есть), blockers[],
warnings[]. Если имплементация противоречит intent тикета — это BLOCKER, даже если код чистый.`

const ALIGNMENT_PROMPT = `Ты reviewer соответствия КОДА архитектуре и существующей кодовой базе
(НЕ аудит доков — смотришь сам код). Изменения — в незакоммиченном дереве.
${SCOPE_TEXT}

1. Дифф: \`${DIFF_CMD}\` + \`${DIFF_STAT_CMD}\` + новые файлы через \`${UNTRACKED_CMD}\`.
   Изменения вне этого пути — чужая работа, их не ревьюй.
2. Контекст архитектуры: тикет ${issuePath} (его «Vertical Slice Layers» и «Module Map
   Impact»), CLAUDE.md §4 (Architecture Constraints), habit-tracker/ARCHITECTURE.md и
   docs/PHASE-*/architecture/**. Пер-сервисных README/ADRs.md рядом с кодом здесь нет —
   не ищи их.
3. Проверь именно ВПИСАННОСТЬ, не стиль. Здесь два юнита (backend, frontend) и монолитный
   бэкенд — границ микросервисов проверять нечего; проверяй целостность вертикального среза:
   - Слои среза согласованы между собой: модель → миграция → crud → схема → API → UI
     говорят об одной и той же сущности одними именами. Поле, появившееся в схеме и не
     доехавшее до UI, — незакрытый срез, а не «доделаем потом».
   - Слои совпадают с соседним кодом: app/models, app/crud, app/schemas, app/api —
     каталога services/ в бэкенде нет, новый слой не заводить.
   - DTO не пропускают domain models наружу; SQLAlchemy 2.0 Mapped[]/mapped_column();
     async без блокирующего I/O в hot path.
   - Миграция обратима, применённую не редактирует, alembic-голова остаётся одна.
   - Имена событий '<owner>.<entity>.<action>'; user-specific данные в PostgreSQL/Redis,
     shared knowledge — в векторное хранилище; вызовы LLM только через orchestration layer.
   - Граница суток считается ОДНИМ способом на весь срез, не по-разному в бэкенде и UI.
   - Переиспользует существующие модули (app/core/**, frontend/lib/**, frontend/components/**)
     или дублирует уже имеющееся?
   - Никаких PII в логах.
4. Дубликат уже существующей логики или разъехавшийся вертикальный срез = BLOCKER.

Верни структуру: verdict, blockers[] (where/what/fix), warnings[].`

// Гейт качества: ловит долг, невидимый для линта, типов и тестов — код работает,
// но никто не понимает, зачем он такой. Контракт режима — antivibe SKILL.md, «Gate Mode».
// Скилл глобальный (~/.claude/skills/antivibe/), в репозиторий не переносится.
const ANTIVIBE_GATE_PROMPT = `Примени скилл antivibe в режиме --gate к текущим изменениям
(\`${DIFF_CMD}\` плюс новые файлы из \`${UNTRACKED_CMD}\`; изменения вне этого пути — чужая
работа, их не трогай). Прочитай ~/.claude/skills/antivibe/SKILL.md, раздел «Gate Mode».
${SCOPE_TEXT}

Не проверяй стиль, типы и тесты — линтер, mypy и тест-сюит это уже сделали. Проверь ровно то,
чего они не видят, по каждому изменённому файлу:
1. Purpose — формулируется ли одной фразой, зачем файл существует.
2. Justification — есть ли реальное требование за каждым неочевидным паттерном (лишний слой,
   кэш, retry, лок, кастомный сериализатор), или он там «на всякий случай».
3. Duplication — не повторяет ли логику, которая уже есть в репо (проверь по графу graphify,
   graphify-out/graph.json, а не по интуиции).
4. Silent failure — проглоченные except/catch, дефолты, прячущие непринятое решение,
   заметки-напоминания без ссылки на тикет.
5. Contradiction — расходится ли код со своим README, ADR или docstring.

Правила вердикта:
- Непонятность = блокер. Некрасивость = НЕ блокер. Не блокируй на вкусовщине по неймингу,
  форматированию или структуре, которую ты написал бы иначе.
- Каждый блокер: where = file:line, what = что именно необъяснимо, fix = конкретное действие.
- Нечего анализировать → APPROVE с пустыми blockers.

Верни структуру: verdict (APPROVE = PASS, REQUEST_CHANGES = BLOCKED), blockers[], warnings[].`

function verdictPrompt(standards, alignment, gate, impl) {
  return `Сведи три независимых ревью одной имплементации в финальный вердикт.

ИМПЛЕМЕНТАЦИЯ (само-отчёт):
${JSON.stringify(impl, null, 2)}

РЕВЬЮ СТАНДАРТОВ:
${JSON.stringify(standards, null, 2)}

РЕВЬЮ СООТВЕТСТВИЯ КОДОВОЙ БАЗЕ:
${JSON.stringify(alignment, null, 2)}

ГЕЙТ ANTIVIBE (понятность и обоснованность кода):
${JSON.stringify(gate, null, 2)}

Правила:
- approved=true ТОЛЬКО если: все три ревью != REQUEST_CHANGES, ни одного блокера,
  acceptanceCovered=true, и ни один feedbackLoop не равен fail (n/a — законно: слой не
  тронут; fail в migrations — та же красная лампа, что fail в tests).
- Блокеры гейта antivibe имеют тот же вес, что блокеры двух других ревью. Не смягчай их
  как «косметику»: именно необъяснённые мелочи и накапливаются в технический долг.
- Иначе approved=false, и в changeRequests[] выпиши конкретные атомарные правки
  (каждый блокер → одна правка с указанием файла), которые имплементер должен внести
  в следующем раунде. Без воды, исполнимые инструкции.`
}

// --- loop --------------------------------------------------------------------

log(`issue-loop: ${issuePath} (maxRounds=${maxRounds}, scope=${scopeDir})`)

let changeRequests = []
let lastVerdict = null
let lastImpl = null
const history = []

// Preflight: тикет может быть уже сделан, заблокирован или помечен human-in-the-loop —
// выясняем до того, как тратить раунды имплементации.
phase('Preflight')
const preflight = await runAgent(PREFLIGHT_PROMPT, { label: 'preflight', phase: 'Preflight', schema: PREFLIGHT_SCHEMA, model: reviewModel })
log(`  preflight: ${preflight?.verdict ?? 'null'} — ${preflight?.summary ?? ''}`)
if (!preflight || preflight.verdict !== 'proceed') {
  return { issue: issuePath, approved: false, stoppedAt: 'preflight', preflight, rounds: 0, history: [] }
}

phase('Plan')
const plan = await runAgent(PLAN_PROMPT(preflight), { label: 'plan', phase: 'Plan', schema: PLAN_SCHEMA, model: reviewModel })
log(`  plan: ${plan?.files?.length ?? 0} файлов, ${plan?.tests?.length ?? 0} тестов`)
if (!plan) {
  return { issue: issuePath, approved: false, stoppedAt: 'plan', preflight, rounds: 0, history: [] }
}

for (let round = 1; round <= maxRounds; round++) {
  log(`— раунд ${round}/${maxRounds}: implement`)
  phase('Implement')
  const impl = await runAgent(implementPrompt(round, changeRequests, plan), {
    label: `implement r${round}`,
    phase: 'Implement',
    schema: IMPLEMENT_SCHEMA,
    model: implementModel,
  })
  lastImpl = impl
  if (!impl) {
    history.push({ round, error: 'implement agent returned null' })
    break
  }
  const be = impl.feedbackLoops?.backend ?? {}
  const fe = impl.feedbackLoops?.frontend ?? {}
  log(`  impl: ${impl.summary} | be lint=${be.lint} types=${be.types} mig=${be.migrations} tests=${be.tests} | fe lint=${fe.lint} types=${fe.types} tests=${fe.tests}`)

  // Красные feedback loops — ревьюить нечего: не жжём три ревью-агента,
  // сразу возвращаем имплементеру на следующий раунд.
  const failedLoops = []
  for (const [layer, loops] of Object.entries(impl.feedbackLoops ?? {})) {
    for (const [name, value] of Object.entries(loops ?? {})) {
      if (value === 'fail') failedLoops.push(`${layer}.${name}`)
    }
  }
  if (failedLoops.length > 0) {
    changeRequests = [`Почини красные feedback loops (${failedLoops.join(', ')}) — прогони их и добейся pass, ничего сверх`]
    history.push({ round, impl, skippedReview: `red loops: ${failedLoops.join(', ')}` })
    log(`✗ раунд ${round}: красные loops (${failedLoops.join(', ')}) — ревью пропущено, возврат имплементеру`)
    if (round === maxRounds) log('maxRounds исчерпан без аппрува — оставляю человеку')
    continue
  }

  // Simplify: агент simplifier (.claude/agents/simplifier.md) проходит по тронутым файлам
  // до ревью, чтобы ревьюеры не тратили раунд на «упростить X». Агент один на оба языка —
  // тикет вертикальный, и Python с TypeScript приезжают в одном срезе. Красные проверки
  // он откатывает сам.
  phase('Simplify')
  // agentType не используем: реестр custom-агентов резолвится из рабочего каталога
  // СЕССИИ, а она может быть запущена не из habit_tracker_ai — тогда 'simplifier'
  // не находится и петля падает на середине (проверено 2026-08-30). Роль вшита
  // в промпт: .claude/agents/simplifier.md остаётся источником, но не зависимостью.
  const simplified = await runAgent(`${SIMPLIFIER_ROLE}\n\n---\n\n${SIMPLIFY_PROMPT(impl)}`, {
    label: `simplify r${round}`, phase: 'Simplify', schema: SIMPLIFY_SCHEMA,
    model: implementModel,
  })
  log(`  simplify: changed=${simplified?.changed ?? 'null'} checks=${simplified?.checks ?? 'null'}`)

  log(`— раунд ${round}: triple review (standards + alignment + antivibe gate)`)
  const [standards, alignment, gate] = await parallel([
    () => runAgent(STANDARDS_PROMPT, { label: `review:standards r${round}`, phase: 'Review', schema: REVIEW_SCHEMA, model: reviewModel }),
    () => runAgent(ALIGNMENT_PROMPT, { label: `review:alignment r${round}`, phase: 'Review', schema: REVIEW_SCHEMA, model: reviewModel }),
    () => runAgent(ANTIVIBE_GATE_PROMPT, { label: `gate:antivibe r${round}`, phase: 'Review', schema: REVIEW_SCHEMA, model: reviewModel }),
  ])

  log(`  review: standards=${standards?.verdict ?? 'null'} alignment=${alignment?.verdict ?? 'null'} gate=${gate?.verdict ?? 'null'}`)

  // Все ревьюеры умерли (null = скип/терминальная ошибка) — вердикт не из чего сводить.
  if (!standards && !alignment && !gate) {
    history.push({ round, impl, error: 'all reviewers returned null' })
    log(`✗ раунд ${round}: все ревьюеры вернули null — останавливаюсь`)
    break
  }

  // NEEDS_DISCUSSION — вопрос к человеку, крутить раунды бессмысленно.
  if (standards?.verdict === 'NEEDS_DISCUSSION' || alignment?.verdict === 'NEEDS_DISCUSSION' || gate?.verdict === 'NEEDS_DISCUSSION') {
    history.push({ round, impl, standards, alignment, gate, stopped: 'NEEDS_DISCUSSION' })
    log(`⏸ раунд ${round}: NEEDS_DISCUSSION — останавливаюсь, нужен человек`)
    lastVerdict = { approved: false, reason: 'NEEDS_DISCUSSION от ревьюера — требуется решение человека', changeRequests: [] }
    break
  }

  phase('Verdict')
  const verdict = await runAgent(verdictPrompt(standards, alignment, gate, impl), {
    label: `verdict r${round}`,
    phase: 'Verdict',
    schema: VERDICT_SCHEMA,
    // Вердикт — судейство над тремя ревью, а не печать кода: идёт с ревью.
    model: reviewModel,
  })
  lastVerdict = verdict
  history.push({ round, impl, simplified, standards, alignment, gate, verdict })

  if (verdict?.approved) {
    log(`✓ раунд ${round}: APPROVED`)
    break
  }
  changeRequests = verdict?.changeRequests ?? []
  log(`✗ раунд ${round}: REQUEST_CHANGES (${changeRequests.length} правок)`)
  if (round === maxRounds) log('maxRounds исчерпан без аппрува — оставляю человеку')
}

// Report: всегда, даже без аппрува — утреннему ревью нужен след и для BLOCKED.
phase('Report')
// Имена тикетов здесь начинаются с числа (89-import-personal-os-...), в alv буквенный
// сегмент перед числом был обязателен. Регулярка покрывает оба формата.
const issueId = (issuePath.split('/').pop() || '')
  .replace(/\.md$/, '')
  .replace(/^(([a-z0-9]*[a-z][a-z0-9]*-)*[0-9]+)(-.*)?$/, '$1')
const reportPath = `.claude/loop-reports/${issueId}.json`
const renderedPath = `.claude/loop-reports/${issueId}.md`
const report = await runAgent(REPORT_PROMPT({
  id: issueId, reportPath, renderedPath, layers: preflight?.layers ?? [],
  approved: !!lastVerdict?.approved, history, preflight,
}), {
  label: 'report', phase: 'Report', schema: REPORT_SCHEMA, model: reviewModel,
})
log(`  report: ${report?.renderedPath || report?.reportPath || 'null'} (${report?.checklistCount ?? 0} пунктов)`)

return {
  issue: issuePath,
  issueId,
  layers: preflight?.layers ?? [],
  scopeDir,
  report,
  approved: !!lastVerdict?.approved,
  rounds: history.length,
  finalVerdict: lastVerdict,
  lastImplementation: lastImpl,
  preflight,
  plan,
  // Next step для человека (вне петли): просмотреть дифф, при approved=true — mv тикета
  // из in-work/ в done/, коммит с Refs #<id>, затем graphify update (CLAUDE.md §2).
  history,
}
