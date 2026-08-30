// issue-swarm — прогон набора тикетов через issue-loop, по зависимостям.
//
// Портировано из alv/.claude/workflows/issue-swarm.js. Там модель простая: один сервис —
// одна петля, стена между петлями — каталог backend/services/<svc>-service, всё едет
// параллельно. Здесь эта модель не работает и не портируется:
//
//  - тикеты вертикальные, скоуп у всех петель один и тот же (habit-tracker/), стены между
//    ними нет. Две петли в одном рабочем дереве будут видеть дифф друг друга и ревьюить
//    чужой код;
//  - зато у тикетов есть настоящий порядок: строка **Blocked by** в теле. В alv её никто
//    не читал, порядок задавал человек.
//
// Поэтому swarm здесь — не «параллельно», а «по порядку»: считает зависимости внутри
// переданного набора, гонит волнами, по умолчанию ПО ОДНОМУ тикету за раз
// (args.concurrency = 1). Больше единицы ставить можно только если каждой петле дан свой
// git worktree — иначе петли перепутают дифф.
//
// Тикеты без frontmatter (статус — имя lifecycle-папки), поля лежат в теле, ссылки на
// блокеры встречаются в двух формах: '**Blocked by**: 108, 99' и '[#108]'. Рантайм Workflow
// файлы читать не умеет (нет ни fs, ни import, ни process — проверено), поэтому шапки
// тикетов разбирает один дешёвый read-only агент в фазе Triage, а порядок из его ответа
// считает уже код.
//
// Запуск:
//   Workflow({ name: 'issue-swarm',
//              args: { issues: ['issues/PHASE-03/backlog/97-inbox-skeleton-clickup-manual-poll.md',
//                               'issues/PHASE-03/backlog/98-inbox-sources-and-allowlist-screen.md'],
//                      maxRounds: 3 } })
//
// Коммиты и перенос тикетов по lifecycle (backlog → in-work → done) — снаружи, после
// просмотра результата. Ни swarm, ни петля этого не делают.

export const meta = {
  name: 'issue-swarm',
  description: 'Run issue-loop over a set of vertical issues in dependency order (Blocked by), sequentially by default',
  whenToUse: 'Есть 2–5 AFK-тикетов, часть из которых блокирует другую, и нужно прогнать их одной командой в правильном порядке.',
  phases: [
    { title: 'Triage', detail: 'read-only: разобрать шапки тикетов, собрать Blocked by и статусы блокеров' },
    { title: 'Swarm', detail: 'issue-loop волнами по зависимостям' },
  ],
}

const _args = typeof args === 'string' ? JSON.parse(args) : args
const issues = _args?.issues
if (!Array.isArray(issues) || issues.length === 0) throw new Error('args.issues (array of issue .md paths) is required')
const maxRounds = _args?.maxRounds ?? 3

// Сколько петель одновременно. 1 — единственное безопасное значение в общем рабочем дереве:
// скоуп у всех петель один (habit-tracker/), фильтр диффа их не разводит. Больше единицы —
// только когда каждой петле дан свой git worktree.
const concurrency = Math.max(1, _args?.concurrency ?? 1)

// В рантайме Workflow нет ни process, ни import — вычислить путь до соседнего issue-loop.js
// нечем, поэтому он вшит абсолютным. Переопределяется args.loopScript. Забыть про него при
// копировании файла в другой репозиторий — значит гонять петлю чужого проекта.
const LOOP_SCRIPT = _args?.loopScript ?? '/Users/daniilbystrov/Documents/MyProj/habit_tracker_ai/.claude/workflows/issue-loop.js'

const TRIAGE_SCHEMA = {
  type: 'object',
  required: ['tickets'],
  properties: {
    tickets: {
      type: 'array',
      items: {
        type: 'object',
        required: ['issue', 'id', 'title', 'type', 'blockedBy', 'openBlockers'],
        properties: {
          issue: { type: 'string', description: 'путь ровно в том виде, в каком он был дан' },
          id: { type: 'string', description: 'номер тикета из имени файла' },
          title: { type: 'string' },
          type: { type: 'string', description: 'AFK | human-in-the-loop | quick-win' },
          typeReason: { type: 'string', description: 'текст в скобках после human-in-the-loop' },
          estimated: { type: 'string', description: 'S | M | L' },
          blockedBy: { type: 'array', items: { type: 'string' }, description: 'номера блокеров' },
          openBlockers: {
            type: 'array', items: { type: 'string' },
            description: 'блокеры, которые НЕ лежат в done/ и не входят в этот прогон',
          },
          layers: { type: 'array', items: { type: 'string' } },
        },
      },
    },
    notes: { type: 'string' },
  },
}

const TRIAGE_PROMPT = `Разбери шапки тикетов перед прогоном. ТОЛЬКО ЧТЕНИЕ: ничего не менять,
код не трогать, тикеты по папкам не двигать, не коммитить.
Bash-команды строго по одной, без '&&', без ';', без пайпов; cwd не менять.

Тикеты:
${issues.map((p) => `- ${p}`).join('\n')}

ФОРМАТ ТИКЕТА (YAML-frontmatter НЕТ ни в одном файле — не ищи его):
- первая строка '# <заголовок>'; номер тикета — в имени файла, не в заголовке;
- '**Type**: AFK' либо '**Type**: human-in-the-loop (<причина>)'. Причину из скобок
  клади в typeReason;
- '**Blocked by**: 108 (планировщик, в котором живёт задание), 99' — сначала список
  номеров, потом свободная проза. Отрежь хвост по первому '—', '.' или ';' и только
  после этого бери числа 1-4 знаков. Если брать числа по всей строке, в блокеры попадут
  ADR-0017, #155 и номера портов. Ссылка на тикет встречается и как '[#108]', и как '108' —
  обе формы это один и тот же номер, дубликаты схлопни;
- '**Estimated**: M (~6 агент-часов)' — значащая только буква S|M|L;
- разделы '## Vertical Slice Layers', '## Module Map Impact', '## Acceptance', '## Out of Scope'.

Номер блокера бери ТОЛЬКО из форм '[#NNN]' и из голых чисел, разделённых запятыми.
Всё, что обёрнуто в обратные кавычки, и всё, что содержит '/', игнорируй целиком.
Пример: в ссылке вида [ PHASE-01/done/53-apply-plan-batch-endpoint.md ], где путь обёрнут
в обратные кавычки, блокера #01 НЕТ — это кусок имени каталога, а не номер тикета.

Для каждого блокера найди, где он лежит:
  'ls issues/PHASE-*/{backlog,in-work,done,rejected,concerns}/<номер>-*.md'
Каталог PRDs/ в поиск НЕ включай: у отчётов своя нумерация, и 02-kontrakt-roya.md
не имеет отношения к тикету #02. Имя папки и есть статус блокера.
Блокер закрыт, только если лежит в done/. В openBlockers положи те блокеры,
которые не в done/ И которых нет среди тикетов этого прогона — их закрывать некому.

layers заполни по разделу «Vertical Slice Layers»: backend, frontend, ios, other.
Ничего не выдумывай: поля нет в тикете — верни пустую строку или пустой список.`

phase('Triage')
const triage = await agent(TRIAGE_PROMPT, { label: 'triage', phase: 'Triage', schema: TRIAGE_SCHEMA, model: _args?.reviewModel ?? _args?.model ?? 'opus' })
if (!triage?.tickets?.length) throw new Error('triage agent не вернул разобранные тикеты — прогон отменён')

// Сопоставляем ответ агента с тем, что просили: гоняем только те пути, которые дал каллер.
const byPath = new Map()
for (const t of triage.tickets) if (issues.includes(t.issue)) byPath.set(t.issue, t)

const dropped = []
// Отсев в два прохода. Первый выбрасывает тикеты, которые сам прогон закрыть не может;
// второй — тех, кто на них стоял. Один проход здесь неверен: тикет, выброшенный как
// human-in-the-loop, исчезал бы из зависимостей вместо того, чтобы утащить зависимых
// за собой, и #168/#169 уезжали бы в первую волну поверх непостроенного #167.
const neverCloses = new Set()
const survived = []
for (const p of issues) {
  const t = byPath.get(p)
  if (!t) { dropped.push({ issue: p, reason: 'triage не вернул разбор этого тикета' }); continue }
  if (t.type && t.type.startsWith('human-in-the-loop')) {
    dropped.push({ issue: p, id: t.id, reason: `human-in-the-loop: ${t.typeReason || 'нужен человек'}` })
    neverCloses.add(String(t.id))
    continue
  }
  if (t.openBlockers?.length) {
    dropped.push({ issue: p, id: t.id, reason: `открытые блокеры вне прогона: ${t.openBlockers.join(', ')}` })
    neverCloses.add(String(t.id))
    continue
  }
  survived.push(t)
}

// Волна отсева расходится по графу: выбывший тикет закрывает дорогу всем, кто на нём стоял.
const runnable = []
let changed = true
let pool = survived
while (changed) {
  changed = false
  const next = []
  for (const t of pool) {
    const blocked = (t.blockedBy ?? []).map(String).filter((b) => neverCloses.has(b))
    if (blocked.length) {
      dropped.push({ issue: t.issue, id: t.id, reason: `блокер не будет закрыт этим прогоном: ${blocked.join(', ')}` })
      neverCloses.add(String(t.id))
      changed = true
      continue
    }
    next.push(t)
  }
  pool = next
}
runnable.push(...pool)

// Зависимости считаем только внутри набора: блокеры снаружи уже отсеяны выше.
const idsInRun = new Set(runnable.map((t) => String(t.id)))
for (const t of runnable) t.deps = (t.blockedBy ?? []).map(String).filter((b) => idsInRun.has(b) && b !== String(t.id))

for (const d of dropped) log(`⨯ пропуск ${d.issue}: ${d.reason}`)
log(`issue-swarm: ${runnable.length} тикетов, по ${concurrency} за волну`)

phase('Swarm')
const done = new Set()
const results = []
const pending = [...runnable]

while (pending.length > 0) {
  const ready = pending.filter((t) => t.deps.every((d) => done.has(d)))
  if (ready.length === 0) {
    // Остались только те, чьи блокеры внутри набора не прошли (или цикл в Blocked by).
    for (const t of pending) {
      const missing = t.deps.filter((d) => !done.has(d))
      dropped.push({ issue: t.issue, id: t.id, reason: `блокеры не закрыты этим прогоном: ${missing.join(', ')}` })
      log(`⨯ пропуск ${t.issue}: блокеры ${missing.join(', ')} не прошли`)
    }
    break
  }

  const wave = ready.slice(0, concurrency)
  for (const t of wave) pending.splice(pending.indexOf(t), 1)
  log(`— волна: ${wave.map((t) => t.id).join(', ')}`)

  const waveResults = await parallel(wave.map((t) => () =>
    workflow({ scriptPath: LOOP_SCRIPT }, { issue: t.issue, maxRounds, setContext: _args?.setContext, startedAt: _args?.startedAt })
      .then((r) => ({ ticket: t, result: r }))
      .catch((e) => ({ ticket: t, error: String(e) }))
  ))

  for (const r of waveResults.filter(Boolean)) {
    results.push(r)
    // Разблокирует зависимые только пройденный тикет: гнать работу поверх не принятой
    // основы — это ревью чужого черновика в следующем тикете.
    if (r.result?.approved) done.add(String(r.ticket.id))
    log(`${r.result?.approved ? '✓' : '✗'} #${r.ticket.id}: ${r.ticket.title ?? r.ticket.issue}${r.error ? ` (error: ${r.error})` : ''}`)
  }
}

const summary = results.map((r) => ({
  issue: r.ticket.issue,
  id: r.ticket.id,
  title: r.ticket.title,
  approved: !!r.result?.approved,
  stoppedAt: r.result?.stoppedAt ?? null,
  rounds: r.result?.rounds ?? 0,
  report: r.result?.report?.renderedPath ?? null,
  error: r.error ?? null,
}))
for (const s of summary) log(`${s.approved ? '✓' : '✗'} #${s.id}: ${s.issue} (${s.stoppedAt ?? `${s.rounds} раундов`})`)

return { summary, dropped, triageNotes: triage.notes ?? '', details: results }
