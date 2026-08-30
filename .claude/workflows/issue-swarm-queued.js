// issue-swarm-queued — та же петля по набору тикетов, но БЕЗ ЖЁСТКОЙ РАЗДАЧИ.
//
// ЧЕМ ОТЛИЧАЕТСЯ ОТ issue-swarm.js. Тот режет готовые тикеты на волны (ready.slice(0,
// concurrency)) и раздаёт их заранее. Дорожка, которой достался L, работает 40 минут;
// соседняя с двумя S освобождается через 20 и стоит до конца волны — простой встроен
// в конструкцию. Здесь тикеты лежат общим списком в очереди, и дорожка берёт следующий
// сама, как только освободилась. Лок в bashs/swarm-queue.py не даёт двоим взять один.
//
// ПОЧЕМУ ОТДЕЛЬНЫЙ ФАЙЛ, А НЕ ПРАВКА issue-swarm.js. Рой идёт прямо сейчас: четыре
// worktree .claude/worktrees/fast-{1..4} на ветках fast-1..fast-4, и LOOP_SCRIPT у всех
// вшит абсолютным путём в ГЛАВНОЕ дерево. Правка работающего файла ломает работающий
// прогон. Старый issue-swarm.js остаётся как есть — он верен для «прогнать набор
// по зависимостям в одном дереве».
//
// КАК ЗАПУСКАЕТСЯ РОЙ. Не одной сессией на четыре дорожки, а ЧЕТЫРЬМЯ сессиями, по одной
// в каждом worktree, и каждая зовёт этот workflow со своим lane:
//   Workflow({ name: 'issue-swarm-queued', args: { lane: 'fast-1' } })
// Все четыре ходят в одну очередь и на одну доску в главном дереве (в worktree ни issues/,
// ни .night/ не существует — оба в .gitignore, git worktree add их не создаёт).
// Первая сессия наполняет очередь (args.issues или args.collect), остальные видят её
// уже полной: fill идемпотентен, повторный вызов ничего не сбивает.
//
// ГЛАВНОЕ ОГРАНИЧЕНИЕ РАНТАЙМА: В Workflow НЕТ fs, import и process — файл прочитать
// нечем (проверено, см. шапку issue-swarm.js). Значит очередь и доску зовёт не скрипт,
// а АГЕНТ через Bash, и результат возвращает структурой по схеме. Отсюда вся форма этого
// файла: на каждый тикет два дешёвых агента (взять / закрыть) вокруг одной тяжёлой петли.
//
// ЧТО ЭТОТ WORKFLOW НЕ ДЕЛАЕТ, как и issue-loop: не коммитит, не двигает тикеты по
// lifecycle-папкам, не сливает ветки. Коммит в свою ветку и слияние — снаружи, руками
// или драйвером дорожки. После слияния веток человек зовёт
// `python3 bashs/swarm-queue.py merged`, и тикеты, чьи блокеры закрыты на слитых ветках,
// становятся доступны остальным дорожкам.

export const meta = {
  name: 'issue-swarm-queued',
  description: 'Lane pulls tickets from a shared ownerless queue until it is empty; facts go on the swarm board',
  whenToUse: 'Идёт рой из нескольких worktree, и надо, чтобы освободившаяся дорожка сама брала следующий тикет, а соседи узнавали о занятых именах сразу.',
  phases: [
    { title: 'Fill', detail: 'наполнить очередь (только если переданы issues или collect)' },
    { title: 'Lane', detail: 'цикл: взять тикет из очереди → issue-loop → закрыть тикет' },
  ],
}

const _args = typeof args === 'string' ? JSON.parse(args) : args

const lane = _args?.lane
if (!lane) throw new Error('args.lane (имя дорожки, например fast-1) обязателен')

const maxRounds = _args?.maxRounds ?? 3
const maxTickets = _args?.maxTickets ?? 20        // предохранитель от бесконечного цикла
const leaseSec = _args?.leaseSec ?? 2700
const maxSize = _args?.maxSize ?? ''              // 'S' в хвосте прогона, когда времени мало

// Абсолютные пути вшиты по той же причине, что LOOP_SCRIPT в issue-swarm.js: вычислить
// их в рантайме нечем. Все три указывают в ГЛАВНОЕ дерево — не в worktree дорожки.
const ROOT = _args?.repoRoot ?? '/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai'
const LOOP_SCRIPT = _args?.loopScript ?? `${ROOT}/.claude/workflows/issue-loop.js`
const QUEUE = _args?.queueCmd ?? `python3 ${ROOT}/bashs/swarm-queue.py`
const BOARD = _args?.boardCmd ?? `python3 ${ROOT}/bashs/swarm-board.py`

const ENV_RULES = `Bash-команды строго по одной: без '&&', без ';', без пайпов, cwd не менять.
Никаких правок файлов в этой фазе: ты только зовёшь команды и читаешь их ответ.`

// --- фаза 1: наполнить очередь ---------------------------------------------------
// Отбор тикетов делает bashs/night-collect.py — тот же код, которым его делает ночной
// прогон. Второй отбор здесь заводить нельзя: два расходящихся фильтра однажды уже
// собрали в автономный прогон тикет с пометкой «НЕ БРАТЬ».

const issues = Array.isArray(_args?.issues) ? _args.issues : []
const collect = !!_args?.collect

if (issues.length || collect) {
  phase('Fill')
  const fillCmd = collect
    ? `${QUEUE} fill --collect --phase ${_args?.phase ?? 'PHASE-03'} --max ${_args?.collectMax ?? 12}`
    : `${QUEUE} fill ${issues.map((p) => `'${p}'`).join(' ')}`
  const fill = await agent(
    `Наполни очередь роя. Выполни РОВНО ОДНУ Bash-команду и верни её вывод как есть:
${fillCmd}

Команда идемпотентна: тикет, уже лежащий в очереди, повторно не заводится, чужие захваты
не сбиваются. Ничего кроме этой команды не делай, файлы не правь.
${ENV_RULES}`,
    {
      label: 'fill', phase: 'Fill', model: _args?.cheapModel ?? 'sonnet',
      schema: {
        type: 'object', required: ['output'],
        properties: { output: { type: 'string' }, added: { type: 'integer' } },
      },
    },
  )
  log(`очередь: ${fill?.output?.split('\n').slice(-1)[0] ?? '?'}`)
}

// --- что дорожка обязана знать про доску ------------------------------------------
// Этот текст едет в issue-loop через args.setContext. Петля подмешивает setContext
// в блок /set КАЖДОГО своего агента (preflight, план, имплементер, simplify, три ревью,
// вердикт, отчёт) — то есть правки самой петли для этого не нужны.
//
// Формулировка «через команду, а не редактором» стоит здесь не для красоты: SCOPE_TEXT
// петли запрещает ПИСАТЬ вне habit-tracker/, и bashs/ с .night/ в этом запрете названы
// поимённо. Доска — единственное исключение, и оно держится ровно на том, что запись
// делается командой: команда пишет атомарно и коротко, редактор затёр бы чужие строки.

const boardRules = (digest) => `
## Доска роя (у тебя есть соседи)

Прямо сейчас тот же habit-tracker/ правят ещё три дорожки, каждая в своём worktree.
Их диффа ты не видишь и не увидишь до слияния веток. Всё, что вы знаете друг о друге,
лежит на доске. Твоя дорожка: ${lane}.

Работа с доской — ТОЛЬКО командами, каждая отдельным Bash-вызовом:
  ${BOARD} brief --lane ${lane}                       что заняли соседи
  ${BOARD} brief --lane ${lane} --like <имя>          занято ли конкретное имя
  ${BOARD} note --lane ${lane} --ticket <id> --state claim --kind <вид> --name <имя> --detail "<строка>"
  ${BOARD} note --lane ${lane} --ticket <id> --state fact  --kind <вид> --name <имя> --detail "<строка>" --use "<что соседи обязаны делать с этим>"
Виды: table, column, migration, endpoint, dto, core-fn, lib-module, component, event,
day-rule, enum, dep, magnet, invariant, debt, conflict (список с пояснениями — в --help).

Это ЕДИНСТВЕННОЕ исключение из запрета писать вне habit-tracker/, и оно про команду,
а не про файл: редактором в bashs/ и .night/ по-прежнему нельзя ничего.

В ФАЗЕ ПЛАНА, до первой строки кода: сначала brief, потом claim на каждое имя, которое
собираешься занять — таблица, колонка, модуль, публичная функция, путь эндпоинта, набор
enum, пакет, файл-магнит (app/main.py, app/models/__init__.py, tests/conftest.py,
frontend/lib/api.ts, lib/routes.ts, docker-compose.yml). Точность не нужна, нужно ИМЯ:
«заведу таблицу work_interval, поля уточню» — полезная запись, молчание до конца работы —
бесполезная. Увидел на доске имя, которое собирался занять сам, — не заводи второе:
таблицу используй чужую, функцию импортируй, эндпоинт расширяй. Уступил — запиши это
(--kind conflict --name <спорное имя> --detail "занято <дорожка>/#<тикет>; беру <новое>"),
иначе через двадцать минут ту же уступку сделает кто-то ещё.

МИГРАЦИИ. Дорожки сидят на разных ветках и видят одну голову alembic. Две ревизии на одну
голову = две головы при слиянии, а это блокер уровня упавших тестов (CLAUDE.md §3).
Прежде чем писать ревизию — brief --kind migration. Кто-то уже объявил ревизию на ту же
голову — не пиши свою: сделай ту часть среза, которая обходится без схемы, а расхождение
верни в moduleMapDelta. Написал — обязательно fact с id ревизии и её down_revision.

ПЕРЕД ТЕМ КАК ЗАВЕСТИ ФАЙЛ в app/core, app/day, app/scheduling или frontend/lib — brief
ещё раз. Соседи объявили свои имена, пока ты писал тесты; хелпер, который ты собрался
написать, там уже может лежать.

В ФАЗЕ ОТЧЁТА переведи свои claim в факты: настоящие поля таблицы, id ревизии, сигнатура
функции, путь эндпоинта и имя схемы ответа, набор значений enum. Отдельно --kind invariant
на каждый запрет и обязанность, которые твоя работа накладывает на тех, кто придёт после
(формулируй приказом: «своей функции локальной даты не заводить — только
app.core.daytime.local_date»). Отдельно --kind debt на то, что ты осознанно НЕ сделал,
чтобы сосед не «починил» это заодно. Прозу, счётчики тестов и разбор приёмки на доску
не писать — доска читается целиком на каждой фазе и обязана остаться короткой.

ЧТО СЕЙЧАС НА ДОСКЕ (снимок на старте тикета; за время работы он устареет — перечитывай):
${digest || '(пусто: ты первый)'}
`.trim()

// --- фаза 2: цикл дорожки ----------------------------------------------------------

phase('Lane')

const TAKE_SCHEMA = {
  type: 'object',
  required: ['took'],
  properties: {
    took: { type: 'boolean', description: 'взят ли тикет' },
    issue: { type: 'string', description: 'абсолютный путь к .md тикета' },
    id: { type: 'string' },
    est: { type: 'string' },
    title: { type: 'string' },
    reason: { type: 'string', description: 'если не взят — что напечатала команда' },
    digest: { type: 'string', description: 'вывод board brief целиком, как есть' },
  },
}

const CLOSE_SCHEMA = {
  type: 'object',
  required: ['closedAs'],
  properties: {
    closedAs: { type: 'string', description: 'done | failed | requeued | stuck' },
    output: { type: 'string' },
  },
}

const results = []
let ticketsDone = 0

while (ticketsDone < maxTickets) {
  // ШАГ 1. Взять тикет и снять снимок доски. Один агент, две Bash-команды: отдельный
  // агент под каждую команду стоил бы вдвое дороже, а решений он не принимает.
  const take = await agent(
    `Возьми следующий тикет из очереди роя для дорожки ${lane} и сними снимок доски.

Команда 1 (взять тикет):
  ${QUEUE} next --lane ${lane} --worktree . --lease-sec ${leaseSec}${maxSize ? ` --max-size ${maxSize}` : ''} --json
Она печатает одну строку JSON вида {"ticket": {...} | null, "reason": "..."}.
Код возврата 3 означает «брать нечего» — это НОРМАЛЬНЫЙ исход, а не сбой: верни
took=false и текст reason. Код 0 — тикет твой: возьми из объекта ticket поля path, id,
est, title и верни их в issue, id, est, title.

Команда 2 (только если тикет взят):
  ${BOARD} brief --lane ${lane}
Верни её вывод в поле digest ЦЕЛИКОМ и дословно, ничего не пересказывая и не сокращая.
Пустой вывод — нормально, значит соседи пока ничего не объявили.

Больше ничего не делай: тикет по папкам не двигай, код не трогай, не коммить.
${ENV_RULES}`,
    { label: `take-${ticketsDone + 1}`, phase: 'Lane', schema: TAKE_SCHEMA, model: _args?.cheapModel ?? 'sonnet' },
  )

  if (!take?.took || !take?.issue) {
    log(`${lane}: очередь кончилась — ${take?.reason ?? 'причина не названа'}`)
    break
  }
  log(`${lane} ← #${take.id} (${take.est || '?'}) ${take.title ?? take.issue}`)

  // ШАГ 2. Петля по тикету. Доска и правила уезжают в неё через setContext — единственный
  // штатный вход петли, который она подмешивает КАЖДОМУ своему агенту. Правок issue-loop.js
  // для этого не нужно, и это намеренно: файл общий для всех четырёх работающих дорожек.
  const setContext = [_args?.setContext ?? '', boardRules(take.digest ?? '')]
    .filter(Boolean).join('\n\n')

  let loop = null
  let loopError = ''
  try {
    loop = await workflow({ scriptPath: LOOP_SCRIPT }, {
      issue: take.issue,
      maxRounds,
      repoRoot: _args?.loopRepoRoot ?? undefined,
      setContext,
      startedAt: _args?.startedAt,
      model: _args?.model,
      implementModel: _args?.implementModel,
      reviewModel: _args?.reviewModel,
    })
  } catch (e) {
    loopError = String(e)
  }

  const approved = !!loop?.approved
  const stoppedAt = loop?.stoppedAt ?? null
  // Четыре разных исхода, и путать их нельзя (это самая дорогая ошибка очереди):
  //  - зелёный вердикт            → done, тикет закрыт;
  //  - обрыв/переполнение контекста → requeue, но ТОЛЬКО своей дорожке: наполовину
  //    сделанная работа лежит в её worktree, соседу отдать нечего;
  //  - blocked / исчерпан maxRounds → failed, в очередь НЕ возвращается: повтор упрётся
  //    в ту же стену и сожжёт агента впустую;
  //  - падение самого workflow       → requeue своей дорожке, разбирается человек.
  const interrupted = !!loopError || stoppedAt === 'context' || stoppedAt === 'error'
  const outcome = approved ? 'done' : (interrupted ? 'requeue' : 'fail')

  // ШАГ 3. Закрыть тикет в очереди и убрать за собой на доске. Снятие claim обязательно:
  // без него доска через две волны состоит из имён, занятых мертвецами, и следующая
  // дорожка уступает имя тому, кого уже нет.
  const closeCmd = outcome === 'done'
    ? `${QUEUE} done --lane ${lane} --id ${take.id} --note "${(loop?.report?.renderedPath ?? '').replace(/"/g, '')}"`
    : outcome === 'requeue'
      ? `${QUEUE} fail --lane ${lane} --id ${take.id} --requeue --reason "прервано: ${(loopError || stoppedAt || 'обрыв').replace(/"/g, '').slice(0, 120)}"`
      : `${QUEUE} fail --lane ${lane} --id ${take.id} --reason "не принято: ${(stoppedAt || 'вердикт не approved').replace(/"/g, '').slice(0, 120)}"`

  const close = await agent(
    `Закрой тикет #${take.id} в очереди роя. Дорожка ${lane}, исход: ${outcome}.

Команда 1:
  ${closeCmd}

${outcome === 'done' ? `Команда 2 — ничего снимать не надо: заявленные имена стали фактами в фазе отчёта петли.
Проверь это одной командой и верни её вывод:
  ${BOARD} brief --lane ${lane} --all-lanes --ticket ${take.id}
Если там остались записи со state=claim, значит фаза отчёта их не перевела в факты —
это finding для человека, сам ничего не дописывай.`
      : `Команда 2 — сними claim этой дорожки по этому тикету, иначе занятые имена
останутся за мертвецом. Сначала посмотри, что было заявлено:
  ${BOARD} brief --lane ${lane} --all-lanes --ticket ${take.id}
и на КАЖДУЮ запись со state=claim выполни отдельной командой:
  ${BOARD} note --lane ${lane} --ticket ${take.id} --state dropped --kind <тот же вид> --name "<то же имя>" --detail "тикет не закрыт: ${outcome}"
Записей claim нет — ничего не делай.`}

Код не трогай, тикет по папкам не двигай, не коммить.
${ENV_RULES}`,
    { label: `close-${take.id}`, phase: 'Lane', schema: CLOSE_SCHEMA, model: _args?.cheapModel ?? 'sonnet' },
  )

  results.push({
    id: take.id, issue: take.issue, title: take.title ?? '',
    approved, stoppedAt, outcome, closedAs: close?.closedAs ?? outcome,
    rounds: loop?.rounds ?? 0, report: loop?.report?.renderedPath ?? null,
    error: loopError || null,
  })
  log(`${approved ? '✓' : '✗'} #${take.id}: ${outcome}${loopError ? ` (${loopError})` : ''}`)
  ticketsDone += 1
}

if (ticketsDone >= maxTickets) log(`${lane}: упёрлись в maxTickets=${maxTickets} — очередь могла остаться непустой`)

return {
  lane,
  taken: results.length,
  approved: results.filter((r) => r.approved).length,
  results,
}
