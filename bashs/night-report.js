#!/usr/bin/env node
// [review:need-review] PHASE-03/night-run
// summary: сводит артефакты ночи в Markdown — страницу на тикет и сводку прогона —
//          в docs/PHASE-03/night-run/<дата>/. Ноль зависимостей, только fs и path.
//
// Почему Markdown, а не порт night-report.js из alv (864 строки HTML):
//   * большая часть того файла существует ради doc-графа: блок <script id="doc-meta">,
//     резолв ADR-036 → узел графа, имя night.html вместо index.html в обход сборщика,
//     дашборд всех ночей. Ни графа, ни docs-html/, ни сервера 8931 здесь нет;
//   * страницы логов сессий там читают ~/.claude/projects/<slug>/*.jsonl. Ночь тут одна
//     сессия на тикет и сырой конверт уже лежит в .night/logs/<id>.attemptN.json —
//     отдельная HTML-страница на это не окупается;
//   * читать 5-8 тикетов утром в Markdown быстрее, чем поднимать сервер. Понадобится
//     страница — в ~/.claude/skills/ есть /academic-html и /paper-html, они рендерят
//     готовый .md одной командой; свой рендерер держать дороже.
//
// Куда пишет: docs/PHASE-03/night-run/<дата>/<id>.md и .../night.md.
// docs/ лежит в git, а issues/ — нет: отчёт о ночи обязан пережить `rm -rf issues/`.
//
// Команды:
//   night   [--date YYYY-MM-DD]   страницы всех тикетов ночи + сводка
//   ticket  <id> [--date ...]     одна страница
//   list    [--date ...]          id тикетов ночи, по одному в строке
//   review  <id> <review.json>    влить утреннее ревью и перерисовать страницу

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const PHASE = 'PHASE-03'
const W = path.join(ROOT, '.night')
const LOOP_REPORTS = path.join(ROOT, '.claude', 'loop-reports')
const outDir = (date) => path.join(ROOT, 'docs', PHASE, 'night-run', date)

const readJson = (p, dflt = null) => {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')) } catch { return dflt }
}
const readText = (p) => { try { return fs.readFileSync(p, 'utf8') } catch { return '' } }
const readTsv = (p) => readText(p).split('\n').filter(Boolean).map((l) => l.split('\t'))

function newestDate() {
  try {
    const dates = fs.readdirSync(W)
      .map((f) => /^night-(\d{4}-\d{2}-\d{2})\.list$/.exec(f))
      .filter(Boolean).map((m) => m[1]).sort()
    if (dates.length) return dates[dates.length - 1]
  } catch { /* каталога ещё нет */ }
  return new Date().toISOString().slice(0, 10)
}

// --- сбор данных ----------------------------------------------------------------

function nightIds(date) {
  const ids = []
  const push = (id) => { if (id && !ids.includes(id)) ids.push(id) }
  // Список волны: тикеты, которые собирались, даже если сессия по ним не стартовала.
  for (const row of readTsv(path.join(W, `night-${date}.tsv`))) push(row[1])
  // summary.tsv шире результатов: сюда попадают RATE_LIMITED, EXHAUSTED, SKIPPED_* —
  // именно те прогоны, которые утром интереснее всего, а отчёта у них нет вовсе.
  for (const row of readTsv(path.join(W, 'summary.tsv'))) {
    if ((row[0] || '').startsWith(date)) push(row[1])
  }
  return ids.sort((a, b) => Number(a) - Number(b))
}

function timingsOf(id) {
  const rows = readTsv(path.join(W, 'timings.tsv')).filter((r) => r[0] === id)
  if (!rows.length) return { attempts: 0, wallSec: 0, statuses: [] }
  const starts = rows.map((r) => Number(r[2])).filter(Number.isFinite)
  const ends = rows.map((r) => Number(r[3])).filter(Number.isFinite)
  return {
    attempts: rows.length,
    wallSec: starts.length && ends.length ? Math.max(...ends) - Math.min(...starts) : 0,
    statuses: rows.map((r) => r[4]),
  }
}

function summaryOf(date, id) {
  const rows = readTsv(path.join(W, 'summary.tsv'))
    .filter((r) => r[1] === id && (r[0] || '').startsWith(date))
  return rows.length ? rows[rows.length - 1] : null
}

function loadTicket(date, id) {
  const report = readJson(path.join(LOOP_REPORTS, `${id}.json`))
  const result = readJson(path.join(W, 'results', `${id}.json`), {})
  const review = readJson(path.join(W, 'reviews', `${id}.json`))
  const sum = summaryOf(date, id)
  return {
    id, report, result, review,
    status: (sum && sum[2]) || result.status || 'НЕТ ДАННЫХ',
    commit: (sum && sum[3]) || result.commit || '',
    note: (sum && sum[4]) || '',
    timings: timingsOf(id),
    handoff: fs.existsSync(path.join(W, 'handoff', `${id}.md`)),
    checks: readText(path.join(W, 'logs', `${id}.checks.log`)),
  }
}

const hms = (sec) => {
  if (!sec || sec < 0) return '—'
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60
  return h ? `${h}ч ${m}м` : m ? `${m}м ${s}с` : `${s}с`
}
const cell = (v) => String(v == null ? '' : v).replace(/\|/g, '\\|').replace(/\n+/g, ' ').trim()

// --- страница тикета -------------------------------------------------------------

function ticketMd(date, t) {
  const r = t.report || {}
  const L = []
  L.push(`# ${t.id} — ${r.title || '(заголовок неизвестен: отчёта петли нет)'}`)
  L.push('')
  L.push(`Ночь ${date}. Статус ${t.status}. Вердикт петли: ${r.verdict || '—'}.`)
  L.push(`Коммит: ${t.commit || 'нет'}. Раундов: ${t.result.rounds ?? r.rounds?.length ?? '—'}. `
    + `Попыток сессии: ${t.timings.attempts || '—'}. Время: ${hms(t.timings.wallSec)}.`)
  if (r.layers?.length) L.push(`Слои: ${r.layers.join(', ')}.`)
  if (r.issuePath) L.push(`Тикет: \`${r.issuePath}\``)
  L.push('')

  if (!t.report) {
    L.push('## Отчёта петли нет')
    L.push('')
    L.push('Фаза Report не отработала: сессия остановилась раньше. Что известно:')
    L.push('')
    L.push(`- статус: ${t.status}${t.note ? ` (${t.note})` : ''}`)
    if (t.result.summary) L.push(`- сессия сказала: ${t.result.summary}`)
    if (t.handoff) L.push(`- есть конспект прерванной сессии: \`.night/handoff/${t.id}.md\``)
    L.push(`- сырые логи попыток: \`.night/logs/${t.id}.attempt*.json\``)
    L.push('')
  } else {
    L.push('## Что сделано')
    L.push('')
    L.push(r.summary || '—')
    L.push('')
    L.push('## Почему так')
    L.push('')
    L.push(r.why || '—')
    L.push('')
    if (r.mermaid) {
      L.push('```mermaid')
      L.push(r.mermaid.trim())
      L.push('```')
      L.push('')
    }
    if (r.files?.length) {
      L.push('## Файлы')
      L.push('')
      L.push('| файл | строки | зачем |')
      L.push('| --- | --- | --- |')
      for (const f of r.files) L.push(`| \`${cell(f.path)}\` | ${cell(f.lines)} | ${cell(f.why)} |`)
      L.push('')
    }
    if (r.adrs?.length) {
      L.push('## Решения (ADR)')
      L.push('')
      for (const a of r.adrs) L.push(`- **${cell(a.id)}** — ${cell(a.why)}`)
      L.push('')
    }
    if (r.tests?.length) {
      L.push('## Тесты')
      L.push('')
      for (const x of r.tests) L.push(`- ${x.status === 'pass' ? 'зелёный' : 'красный'} — ${cell(x.name)}`)
      L.push('')
    }
    if (r.rounds?.length) {
      L.push('## Раунды петли')
      L.push('')
      L.push('| раунд | стандарты | вписанность | antivibe | вердикт | главный блокер |')
      L.push('| --- | --- | --- | --- | --- | --- |')
      for (const x of r.rounds) {
        L.push(`| ${cell(x.round)} | ${cell(x.standards)} | ${cell(x.alignment)} | ${cell(x.antivibe)} | ${cell(x.verdict)} | ${cell(x.note)} |`)
      }
      L.push('')
    }
    if (r.errors?.length) {
      L.push('## Ошибки и остановки')
      L.push('')
      for (const e of r.errors) L.push(`- **${cell(e.phase)}** — ${cell(e.message)}`)
      L.push('')
    }
  }

  if (t.result.blockers?.length) {
    L.push('## Блокеры')
    L.push('')
    for (const b of t.result.blockers) L.push(`- ${cell(b)}`)
    L.push('')
  }

  // Чек-лист рождается ночью (фаза Report), результаты в него проставляет утро.
  // Сшивка по ДОСЛОВНОМУ тексту пункта — поэтому утренний промпт требует копировать текст.
  const checklist = t.report?.checklist || []
  if (checklist.length) {
    const done = new Map((t.review?.checklist || []).map((c) => [c.text, c]))
    L.push('## Чек-лист ревьюера')
    L.push('')
    for (const c of checklist) {
      const d = done.get(c.text)
      const mark = d?.result === 'ok' ? 'x' : ' '
      const tail = d ? ` — **${d.result}**${d.note ? `, ${cell(d.note)}` : ''}` : ''
      L.push(`- [${mark}] (${c.kind}) ${cell(c.text)}${tail}`)
    }
    L.push('')
  }

  L.push('## Утреннее ревью')
  L.push('')
  if (!t.review) {
    L.push('Ещё не проводилось.')
  } else {
    const v = t.review
    L.push(`Вердикт: **${v.verdict}**. Время ревью: ${hms(v.elapsedSec)}, строк диффа: ${v.diffLines ?? '—'}.`)
    L.push('')
    if (v.findings?.length) {
      L.push('| важность | место | что не так | что сделать |')
      L.push('| --- | --- | --- | --- |')
      for (const f of v.findings) {
        L.push(`| ${cell(f.severity)} | \`${cell(f.file)}:${cell(f.line)}\` | ${cell(f.what)} | ${cell(f.fix)} |`)
      }
      L.push('')
    } else {
      L.push('Находок нет.')
      L.push('')
    }
    if (v.humanDecision) L.push(`Решить человеку: ${cell(v.humanDecision)}`)
  }
  L.push('')

  L.push('## Источники')
  L.push('')
  L.push(`- отчёт петли: \`.claude/loop-reports/${t.id}.json\`, \`.claude/loop-reports/${t.id}.md\``)
  L.push(`- результат сессии: \`.night/results/${t.id}.json\``)
  L.push(`- логи попыток: \`.night/logs/${t.id}.attempt*.json\`, \`.night/logs/${t.id}.log\``)
  if (t.checks) L.push(`- проверки перед коммитом: \`.night/logs/${t.id}.checks.log\``)
  if (t.handoff) L.push(`- конспект прерванной сессии: \`.night/handoff/${t.id}.md\``)
  if (t.commit) L.push(`- дифф: \`git show ${t.commit}\``)
  L.push('')
  return L.join('\n')
}

function renderTicket(date, id) {
  const t = loadTicket(date, id)
  const dir = outDir(date)
  fs.mkdirSync(dir, { recursive: true })
  const p = path.join(dir, `${id}.md`)
  fs.writeFileSync(p, ticketMd(date, t))
  return { path: p, ticket: t }
}

// --- сводка ночи ------------------------------------------------------------------

function nightMd(date, tickets) {
  const L = []
  const startRef = readText(path.join(W, `night-${date}.start`)).trim()
  const passed = tickets.filter((t) => t.status === 'PASS')
  const dropped = readTsv(path.join(W, `night-${date}.dropped.tsv`))
  const moves = readTsv(path.join(W, 'moves.tsv')).filter((r) => (r[0] || '').startsWith(date))
  const reviewSec = tickets.reduce((a, t) => a + (t.review?.elapsedSec || 0), 0)
  const loopSec = tickets.reduce((a, t) => a + (t.timings.wallSec || 0), 0)

  L.push(`# Ночной прогон ${date}`)
  L.push('')
  L.push(`Ветка \`phase-03\`. Тикетов взято: ${tickets.length}, прошло: ${passed.length}.`)
  if (startRef) L.push(`Диапазон коммитов: \`${startRef.slice(0, 8)}..HEAD\` (\`git log ${startRef}..HEAD\`).`)
  L.push(`Суммарное время петель: ${hms(loopSec)}. Суммарное время утреннего ревью: ${hms(reviewSec)}.`)
  L.push('')

  L.push('## Тикеты')
  L.push('')
  L.push('| id | статус | ревью | коммит | раундов | попыток | время | страница |')
  L.push('| --- | --- | --- | --- | --- | --- | --- | --- |')
  for (const t of tickets) {
    L.push(`| ${t.id} | ${cell(t.status)} | ${cell(t.review?.verdict || '—')} | `
      + `${t.commit ? `\`${t.commit}\`` : '—'} | ${cell(t.result.rounds ?? '—')} | `
      + `${t.timings.attempts || '—'} | ${hms(t.timings.wallSec)} | [${t.id}.md](./${t.id}.md) |`)
  }
  L.push('')

  const blocked = tickets.filter((t) => t.status !== 'PASS' && t.status !== 'ALREADY_DONE')
  if (blocked.length) {
    L.push('## Не доехали')
    L.push('')
    for (const t of blocked) {
      L.push(`- **${t.id}** (${t.status}) — ${cell(t.result.summary || t.note || 'причина в логах')}`)
      for (const b of t.result.blockers || []) L.push(`  - ${cell(b)}`)
    }
    L.push('')
  }

  // Переносы тикетов — единственное место, где они переживают `rm -rf issues/`:
  // каталог issues/ первой строкой в .gitignore, mv не оставляет следа в истории.
  if (moves.length) {
    L.push('## Переносы тикетов')
    L.push('')
    L.push('| время | id | откуда | куда | почему |')
    L.push('| --- | --- | --- | --- | --- |')
    for (const m of moves) L.push(`| ${cell(m[0])} | ${cell(m[1])} | ${cell(m[2])} | ${cell(m[3])} | ${cell(m[4])} |`)
    L.push('')
  }

  if (dropped.length) {
    L.push('## Отсеяно при сборе')
    L.push('')
    L.push('| id | причина | подробность |')
    L.push('| --- | --- | --- |')
    for (const d of dropped) L.push(`| ${cell(d[0])} | ${cell(d[1])} | ${cell(d[2])} |`)
    L.push('')
  }

  const errs = tickets.flatMap((t) => (t.report?.errors || []).map((e) => ({ id: t.id, ...e })))
  if (errs.length) {
    L.push('## Ошибки и остановки внутри петель')
    L.push('')
    for (const e of errs) L.push(`- **${e.id}** / ${cell(e.phase)} — ${cell(e.message)}`)
    L.push('')
  }

  const human = tickets
    .map((t) => ({ id: t.id, what: t.review?.humanDecision || (t.status !== 'PASS' ? (t.result.blockers || [])[0] : '') }))
    .filter((x) => x.what)
  L.push('## Что решить человеку')
  L.push('')
  if (human.length) for (const x of human) L.push(`- **${x.id}** — ${cell(x.what)}`)
  else L.push('Ничего: все тикеты либо прошли, либо остановились по понятной причине.')
  L.push('')

  const findings = tickets.flatMap((t) => (t.review?.findings || []).map((f) => ({ id: t.id, ...f })))
  const critical = findings.filter((f) => f.severity === 'critical' || f.severity === 'high')
  L.push('## Безопасно мержить')
  L.push('')
  if (!tickets.some((t) => t.review)) L.push('Утреннее ревью ещё не проводилось — судить рано.')
  else if (critical.length) {
    L.push('Нет: есть находки уровня critical/high.')
    L.push('')
    for (const f of critical) L.push(`- **${f.id}** \`${cell(f.file)}:${cell(f.line)}\` — ${cell(f.what)}`)
  } else L.push('Да: находок уровня critical/high нет.')
  L.push('')
  return L.join('\n')
}

function renderNight(date) {
  const ids = nightIds(date)
  const dir = outDir(date)
  fs.mkdirSync(dir, { recursive: true })
  const tickets = ids.map((id) => renderTicket(date, id).ticket)
  const p = path.join(dir, 'night.md')
  fs.writeFileSync(p, nightMd(date, tickets))
  return { path: p, count: ids.length }
}

// --- команды ------------------------------------------------------------------------

const argv = process.argv.slice(2)
const rest = []
let dateArg = ''
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--date') { dateArg = argv[++i] || ''; continue }
  rest.push(argv[i])
}
const date = dateArg || newestDate()
const cmd = rest[0]

switch (cmd) {
  case 'night': {
    const { path: p, count } = renderNight(date)
    console.log(`сводка ночи ${date}: ${count} тикетов → ${path.relative(ROOT, p)}`)
    break
  }
  case 'ticket': {
    const id = rest[1]
    if (!id) { console.error('нужен id тикета'); process.exit(1) }
    const { path: p } = renderTicket(date, id)
    console.log(`страница тикета → ${path.relative(ROOT, p)}`)
    break
  }
  case 'list':
    for (const id of nightIds(date)) console.log(id)
    break
  case 'review': {
    const id = rest[1]
    const file = rest[2]
    if (!id || !file) { console.error('нужны id и путь к review.json'); process.exit(1) }
    const incoming = readJson(file)
    if (!incoming) { console.error(`не читается ${file}`); process.exit(1) }
    const dst = path.join(W, 'reviews', `${id}.json`)
    fs.mkdirSync(path.dirname(dst), { recursive: true })
    fs.writeFileSync(dst, JSON.stringify({ ...(readJson(dst) || {}), ...incoming }, null, 1))
    const { path: p } = renderTicket(date, id)
    console.log(`ревью ${id} влито → ${path.relative(ROOT, p)}`)
    break
  }
  default:
    console.log(readText(__filename).split('\n').slice(1, 28).join('\n'))
    process.exit(1)
}
