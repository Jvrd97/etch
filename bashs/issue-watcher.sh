#!/usr/bin/env bash
# [review:need-review] PHASE-03/night-run
# summary: драйвер ночи — одна headless-сессия claude на тикет, СТРОГО ПО ОДНОМУ тикету,
#          переживает падения API (resume/backoff) и переполнение контекста (handoff),
#          после зелёных проверок сам коммитит и двигает тикет в done/.
#
# Запуск:
#   bashs/issue-watcher.sh [-r 4] [-b 12] [--ask-perms] [-f list.txt] [issue.md ...]
#     -r N          попыток на тикет, включая resume (по умолчанию 4)
#     -b USD        --max-budget-usd на сессию (по умолчанию 12)
#     --ask-perms   НЕ отключать проверку прав (по умолчанию она отключена, см. ниже)
#     -f FILE       файл со списком путей к тикетам, по одному в строке
#
# ГЛАВНАЯ АДАПТАЦИЯ ОТ alv: ФЛАГА -j НЕТ ВОВСЕ.
# В alv тикеты идут в пять потоков, а стена между ними — каталог сервиса
# (backend/services/<svc>-service): два агента физически не встречаются в одних файлах.
# Здесь worktree сняты намеренно (мало места на диске), тикеты вертикальные, скоуп у всех
# один — habit-tracker/. Две сессии в одном дереве перетопчут друг другу файлы, тесты и
# git add, и утренний дифф будет нечитаем. Поэтому цикл последовательный, а лок один
# глобальный — он защищает не сервис, а само рабочее дерево от второго прогона.
#
# ВТОРАЯ АДАПТАЦИЯ: КОММИТИТ И ДВИГАЕТ ТИКЕТ BASH, А НЕ АГЕНТ.
# В alv это делает сессия по ШАГУ 2 промпта. Здесь issue-loop.js по контракту не коммитит
# и не двигает тикет, а `git add .` затянул бы .claude/loop-reports/ (он НЕ в .gitignore).
# Детерминированные шаги дешевле держать в bash: он знает статус, ставит `git add` строго
# по habit-tracker/, гоняет проверки перед коммитом и никогда не делает push.
#
# ТРЕТЬЯ АДАПТАЦИЯ: ДЕРЕВО ОБЯЗАНО ОСТАТЬСЯ ЧИСТЫМ ПОСЛЕ КАЖДОГО ТИКЕТА.
# Одно дерево на всех — значит незакоммиченные правки упавшего тикета попали бы в дифф
# следующего и сломали бы ему тесты. Поэтому: зелёные проверки → коммит; всё остальное →
# `git stash push -u` с именем ночи. Работа не теряется (git stash list), дерево чистое.
#
# Состояние (всё под .night/, каталог в .gitignore):
#   handoff/<id>.md         конспект прерванной сессии для следующей
#   results/<id>.json       вердикт сессии: PASS|BLOCKED|NEEDS_HUMAN|ALREADY_DONE|CONTINUE
#   logs/<id>.attemptN.json сырой JSON-конверт попытки; logs/<id>.log — stderr и проверки
#   summary.tsv             строка на завершённый тикет
#   timings.tsv             строка на попытку
#   moves.tsv               журнал переносов тикетов (issues/ вне git — это единственный след)
#   live/<id>.json          признак «сессия идёт прямо сейчас»
#
# Код выхода 0, когда каждый тикет получил финальный статус, иначе 1.

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

PHASE="PHASE-03"
SCOPE="habit-tracker"
BACKEND_DIR="$SCOPE/services/backend"
FRONTEND_DIR="$SCOPE/services/frontend"
W="$ROOT/.night"
DATE="$(date +%F)"

RETRIES=4; BUDGET="${NIGHT_BUDGET:-12}"; SKIP_PERMS=1; LIST=""
ISSUES=()
while [ $# -gt 0 ]; do
  case "$1" in
    -r) RETRIES="$2"; shift 2 ;;
    -b) BUDGET="$2"; shift 2 ;;
    --ask-perms) SKIP_PERMS=0; shift ;;
    -f) LIST="$2"; shift 2 ;;
    -j) [ "$2" = 1 ] || { echo "-j принимает только 1: рабочее дерево одно"; exit 1; }; shift 2 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) ISSUES+=("$1"); shift ;;
  esac
done
if [ -n "$LIST" ]; then
  while IFS= read -r line; do [ -n "$line" ] && ISSUES+=("$line"); done < "$LIST"
fi
[ ${#ISSUES[@]} -eq 0 ] && { echo "не передано ни одного тикета"; exit 1; }

mkdir -p "$W/handoff" "$W/results" "$W/logs" "$W/live" "$W/reviews"
SUMMARY="$W/summary.tsv"; TIMINGS="$W/timings.tsv"; MOVES="$W/moves.tsv"
touch "$SUMMARY" "$TIMINGS" "$MOVES"

MODEL="${NIGHT_MODEL:-opus}"

# Права. --dangerously-skip-permissions по умолчанию, и это не украшение: acceptEdits
# подтверждает только правки файлов, а первая же Bash-команда вне allow-списка поднимает
# промпт разрешения — отвечать некому, сессия висит до бюджета. В .claude/settings.json
# в ask лежат ровно те команды, без которых ночь не обходится: alembic upgrade head,
# alembic downgrade, git rebase.
# ЧЕМ РИСКУЕМ, ЧЕСТНО: флаг снимает и deny-список тоже. Ночная сессия может выполнить
# rm -rf, sudo, git push --force и цель `make f-git` корневого Makefile (git add . +
# push origin main) — харнесс их больше не держит. Единственная граница — текст промпта
# (SCOPE, запрет push/cd/worktree/make) и то, что коммит делает не агент, а этот скрипт.
# Кому такая цена не нравится — --ask-perms и человек рядом; автономного прогона не будет.
if [ "$SKIP_PERMS" = 1 ]; then PERM_FLAGS=(--dangerously-skip-permissions)
else PERM_FLAGS=(--permission-mode acceptEdits); fi

# Stop-хук check-feedback-loops.sh возвращает decision:block. Сейчас он не срабатывает
# (его фильтр считает пути от корня, а всё лежит под habit-tracker/), но стоит путям
# поменяться — он начнёт драться с откатами фазы Simplify внутри автономной сессии.
export CLAUDE_SKIP_FEEDBACK_CHECK=1
# Полный pytest бэкенда в 120 с не влезает, а таймаут выглядит для агента как красный
# feedback loop и жжёт раунд впустую. В settings.json не лезем: там значение для дневных
# сессий человека.
export BASH_DEFAULT_TIMEOUT_MS="${BASH_DEFAULT_TIMEOUT_MS:-600000}"

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }
json_field() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); v=d.get(sys.argv[2],""); print("" if v is None else v)' "$1" "$2" 2>/dev/null; }
result_status() { json_field "$1" status; }

# --- /set: сборка окружения, одна на прогон ------------------------------------
# Скилл ~/.claude/skills/set/SKILL.md человек проходит руками в начале сессии. Ночью
# человека нет, а агенты петли стартуют с пустым контекстом. Общий генератор блока —
# ~/.claude/bin/set-context.sh; он считает ветку, HEAD и режим дня по ТЕКУЩЕМУ каталогу,
# поэтому вызывается строго из корня habit_tracker_ai, иначе в контекст уедет чужое репо.
SET_CONTEXT="$( cd "$ROOT" && { "$HOME/.claude/bin/set-context.sh" 2>/dev/null; cat <<'EOF'
Прогон автономный: человека рядом нет, вопросов задавать некому — спорное решение
записывается как finding или blocker, а не выбирается наугад.
Тикеты идут строго по одному в общем рабочем дереве: worktree в этом проекте нет.
Ты единственный, кто сейчас правит habit-tracker/ — но и убрать за собой некому.
Каноны проекта действуют: .claude/CLAUDE.md, документация по-русски, код по-английски.
Коммит и перенос тикета делает ночной скрипт после зелёных проверок, не ты.
EOF
} )"
SET_CONTEXT_JSON="$(printf '%s' "$SET_CONTEXT" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"

# --- глобальный лок ------------------------------------------------------------
# Лок один на репозиторий, а не на сервис: он защищает рабочее дерево от второго прогона.
LOCK="$W/lock"
lock_owner_alive() { local pid; pid="$(cat "$1/pid" 2>/dev/null)" || return 1; [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; }
if ! mkdir "$LOCK" 2>/dev/null; then
  if lock_owner_alive "$LOCK"; then
    echo "другой ночной прогон уже идёт (pid $(cat "$LOCK/pid" 2>/dev/null)) — выходим"; exit 1
  fi
  log "лок протух, забираю"; rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null; mkdir "$LOCK" 2>/dev/null
fi
echo $$ > "$LOCK/pid"
trap 'rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null' EXIT
rm -f "$W"/live/*.json 2>/dev/null

# Ставится при первом же HTTP 429: квота у аккаунта общая, остальные тикеты упрутся в ту
# же стену. Без флага один лимит превращается в шесть попыток на каждый оставшийся тикет.
RATE_LIMIT_FLAG="$W/ratelimit.stop"
rm -f "$RATE_LIMIT_FLAG"

issue_id() { basename "$1" .md | sed -E 's/^([0-9]+)(-.*)?$/\1/'; }

# --- проверки перед коммитом ----------------------------------------------------
# Гоняются те слои, файлы которых реально тронуты. Команды — те же, что в
# .claude/workflows/issue-loop.js: docker-демон на этой машине не поднят, поэтому
# make check / make test / make db не используются, порт 5432 вместо 5433.
touched() { [ -n "$(git -C "$ROOT" status --porcelain -- "$1")" ]; }

run_check() {  # $1 = имя, дальше команда
  local name="$1"; shift
  printf '--- %s: %s\n' "$name" "$*" >> "$CHECKLOG"
  if "$@" >> "$CHECKLOG" 2>&1; then printf '    OK\n' >> "$CHECKLOG"; return 0; fi
  printf '    RED\n' >> "$CHECKLOG"; log "[$ID] красная проверка: $name"; return 1
}

gate_checks() {
  local red=0 heads
  : > "$CHECKLOG"
  if touched "$BACKEND_DIR"; then
    run_check "ruff check"  uv run --directory "$BACKEND_DIR" ruff check app tests || red=1
    run_check "ruff format" uv run --directory "$BACKEND_DIR" ruff format --check app tests || red=1
    run_check "mypy"        uv run --directory "$BACKEND_DIR" mypy --strict app || red=1
    # Две alembic-головы — такой же блокер, как упавшие тесты (CLAUDE.md §3).
    heads="$(uv run --directory "$BACKEND_DIR" alembic heads 2>>"$CHECKLOG" | grep -c '[^[:space:]]')"
    printf -- '--- alembic heads: %s\n' "$heads" >> "$CHECKLOG"
    [ "$heads" = 1 ] || { red=1; log "[$ID] alembic heads = $heads, ожидалась одна"; }
    run_check "pytest" env POSTGRES_HOST=localhost POSTGRES_PORT=5432 \
      TEST_DATABASE_URL=postgresql+asyncpg://habit_user:habit_pass@localhost:5432/habit_tracker_test \
      uv run --directory "$BACKEND_DIR" pytest tests/ -q || red=1
  fi
  if touched "$FRONTEND_DIR"; then
    run_check "bun test" bun --cwd="$ROOT/$FRONTEND_DIR" test || red=1
    run_check "tsc"      bunx tsc -p "$FRONTEND_DIR/tsconfig.json" --noEmit || red=1
    run_check "lint"     bun --cwd="$ROOT/$FRONTEND_DIR" run lint || red=1
  fi
  return $red
}

# --- перенос тикета и уборка дерева ---------------------------------------------
# issues/ первой строкой в .gitignore: перенос — обычный mv, не git mv, и он никуда не
# коммитится. Журнал moves.tsv и сводка ночи в docs/ — единственный след, который
# переживёт `rm -rf issues/`.
move_ticket() {  # $1 = путь, $2 = целевая папка, $3 = причина
  local issue="$1" dest_dir="$2" why="$3" rel dest
  rel="${issue#$ROOT/}"
  case "$rel" in */in-work/*) ;; *) return 0 ;; esac
  dest="$(printf '%s' "$rel" | sed "s|/in-work/|/$dest_dir/|")"
  mkdir -p "$(dirname "$ROOT/$dest")"
  mv "$issue" "$ROOT/$dest" 2>/dev/null || return 0
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$(issue_id "$issue")" "in-work" "$dest_dir" "$why" >> "$MOVES"
  log "[$(issue_id "$issue")] тикет → $dest_dir/"
}

park_worktree() {  # $1 = id, $2 = почему
  [ -n "$(git -C "$ROOT" status --porcelain -- "$SCOPE")" ] || return 0
  local msg="night-$DATE $1 $2"
  if git -C "$ROOT" stash push -u -m "$msg" -- "$SCOPE" >/dev/null 2>&1; then
    log "[$1] незакоммиченная работа убрана в stash: $msg"
    printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$1" "worktree" "stash" "$msg" >> "$MOVES"
  else
    log "[$1] ВНИМАНИЕ: не удалось убрать дерево в stash — следующий тикет не запускаю"
    : > "$W/dirty.stop"
  fi
}

# --- коммит ---------------------------------------------------------------------
commit_ticket() {  # $1 = id, $2 = subject; печатает hash или пусто
  local id="$1" subject="$2"
  git -C "$ROOT" add -- "$SCOPE" >/dev/null 2>&1
  if git -C "$ROOT" diff --cached --quiet; then echo ""; return 1; fi
  git -C "$ROOT" commit -q -m "$subject" -m "Refs $PHASE/$id" >>"$LOGF" 2>&1 || { echo ""; return 1; }
  git -C "$ROOT" rev-parse --short HEAD
}

# --- промпт сессии --------------------------------------------------------------
build_prompt() {
  local issue="$1" id="$2" handoff="$3" result="$4" mode="$5" step1
  if [ "$mode" = direct ]; then
    step1="ШАГ 1. Инструментом Workflow НЕ пользуйся: в прошлой попытке сессия запустила его
в фоне и умерла вместе с ним. Проведи петлю сам, тем же контрактом, что
.claude/workflows/issue-loop.js: preflight → план → реализация по TDD → упрощение →
три ревью (стандарты, вписанность в кодовую базу, antivibe-гейт) → вердикт → отчёт.
Отчёт положи в .claude/loop-reports/$id.json и .claude/loop-reports/$id.md той же
структурой, что описана в REPORT_PROMPT этого файла — прочитай его и следуй ему."
  else
    step1="ШАГ 1. Запусти workflow:
Workflow({ scriptPath: \"$ROOT/.claude/workflows/issue-loop.js\",
  args: { issue: \"$issue\", maxRounds: 3, repoRoot: \"$ROOT\", scopeDir: \"$SCOPE\",
          startedAt: \"$(date -u +%FT%TZ)\", setContext: $SET_CONTEXT_JSON } })
Инструмент возвращает id задачи СРАЗУ, работа идёт в фоне. Твоя единственная задача
дальше — дождаться её конца: опрашивай TaskOutput или TaskGet по этому id, пока задача
не завершится, и только потом переходи к ШАГУ 2. Не заканчивай ход раньше: workflow
умирает вместе с сессией. Ответ вида «workflow запущен, жду» — это провал сессии, а не
результат. Если Workflow или TaskOutput недоступны — проведи петлю сам тем же контрактом."
  fi
  cat <<EOF
Ты ведёшь РОВНО ОДИН тикет без участия человека: $issue (id $PHASE/$id).
Репо: $ROOT, ветка phase-03. Работай из корня репо: cwd не менять, worktree не создавать,
push не делать, make не запускать.

$SET_CONTEXT

ШАГ 0. Если существует файл $handoff — прочитай его ПЕРВЫМ. Это конспект предыдущей
сессии по этому же тикету: продолжай ровно с описанного места, не начинай заново и не
повторяй сделанное (сверься с git status -- $SCOPE).
$( [ "$mode" = resume ] && echo "Эта сессия — продолжение после обрыва по ошибке API. Сначала посмотри, что уже лежит в рабочем дереве, потом продолжай." )

$step1

ШАГ 2. НЕ КОММИТЬ и НЕ ДВИГАТЬ ТИКЕТ по папкам. Это делает ночной скрипт после того, как
сам прогонит проверки: он ставит git add строго по $SCOPE/ (git add . затянул бы
.claude/loop-reports/, который не в .gitignore) и переносит тикет в done/ обычным mv.
Твоя работа заканчивается файлом результата.

ШАГ 3. Запиши $result строго в этой форме:
{"issue":"$issue","id":"$id","status":"PASS|BLOCKED|NEEDS_HUMAN|ALREADY_DONE|CONTINUE",
 "commitSubject":"feat(<тема одним-двумя словами>): $PHASE/$id <короткий заголовок>",
 "rounds":<число раундов петли>,"blockers":["<до трёх строк>"],
 "summary":"<1-2 предложения: что появилось в поведении системы>"}
Соответствие статусов: вердикт approved → PASS; preflight already-done → ALREADY_DONE
(и тогда commitSubject пустой); preflight blocked, NEEDS_DISCUSSION или исчерпание
maxRounds без аппрува → BLOCKED; нужен человек (доступ, токен, решение) → NEEDS_HUMAN.

ПРАВИЛО КОНТЕКСТА И СБОЕВ. Если твой контекст заполнен больше чем наполовину, или
workflow либо агент упал с ошибкой API, лимита или таймаута — НЕ продолжай работу.
Вместо этого: (1) запиши подробный конспект в $handoff — что именно сделано, какие файлы
тронуты и в каком они состоянии, какие проверки зелёные и какие красные, на какой фазе
петли остановились, какой ТОЧНЫЙ следующий шаг; (2) запиши $result со status CONTINUE;
(3) закончи ход. Следующая сессия стартует с этого конспекта, а не с нуля.

Ответ в чат — одна строка со статусом. Подробности только в файлах.
EOF
}

# --- один тикет -----------------------------------------------------------------
run_issue() {
  local issue="$1"
  local handoff result attempt=0 mode=fresh session_id="" status="" resume_streak=0
  ID="$(issue_id "$issue")"
  handoff="$W/handoff/$ID.md"; result="$W/results/$ID.json"
  LOGF="$W/logs/$ID.log"; CHECKLOG="$W/logs/$ID.checks.log"

  if [ -f "$RATE_LIMIT_FLAG" ]; then
    log "[$ID] пропущен: лимит аккаунта"
    printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$ID" "SKIPPED_RATE_LIMIT" "" "" >> "$SUMMARY"
    return 0
  fi
  if [ -f "$W/dirty.stop" ]; then
    log "[$ID] пропущен: предыдущий тикет оставил дерево грязным"
    printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$ID" "SKIPPED_DIRTY_TREE" "" "" >> "$SUMMARY"
    return 1
  fi

  # Вердикт уже на диске с прошлой ночи, а тикет остался в in-work/: сессия не нужна,
  # нужен перенос — иначе он собирается каждую ночь заново.
  if [ -f "$result" ]; then
    status="$(result_status "$result")"
    case "$status" in
      PASS|ALREADY_DONE) move_ticket "$issue" done "вердикт $status с прошлого прогона" ;;
    esac
    case "$status" in PASS|BLOCKED|NEEDS_HUMAN|ALREADY_DONE)
      log "[$ID] уже финальный: $status"; return 0 ;;
    esac
  fi

  while [ "$attempt" -lt "$RETRIES" ]; do
    [ -f "$RATE_LIMIT_FLAG" ] && { log "[$ID] стоп: лимит аккаунта"; return 0; }
    attempt=$((attempt+1))
    rm -f "$result"
    log "[$ID] попытка $attempt/$RETRIES ($mode)"
    local out="$W/logs/$ID.attempt$attempt.json"
    local t0; t0="$(date +%s)"
    printf '{"id":"%s","attempt":%s,"mode":"%s","startedAt":%s}\n' "$ID" "$attempt" "$mode" "$t0" > "$W/live/$ID.json"
    # --name связывает процесс с тикетом в реестре `claude agents --json`.
    if [ "$mode" = resume ] && [ -n "$session_id" ]; then
      claude -p --name "night-$ID" --resume "$session_id" --output-format json --model "$MODEL" \
        --max-budget-usd "$BUDGET" "${PERM_FLAGS[@]}" \
        "Сессия оборвалась. $(build_prompt "$issue" "$ID" "$handoff" "$result" resume)" > "$out" 2>>"$LOGF"
    else
      claude -p --name "night-$ID" --output-format json --model "$MODEL" \
        --max-budget-usd "$BUDGET" "${PERM_FLAGS[@]}" \
        "$(build_prompt "$issue" "$ID" "$handoff" "$result" "$mode")" > "$out" 2>>"$LOGF"
    fi
    local rc=$?
    rm -f "$W/live/$ID.json"
    session_id="$(json_field "$out" session_id)"
    status="$( [ -f "$result" ] && result_status "$result" )"

    if [ "$(json_field "$out" api_error_status)" = "429" ]; then
      : > "$RATE_LIMIT_FLAG"
      log "[$ID] лимит (429) — останавливаю весь прогон"
      park_worktree "$ID" "rate-limited"
      printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$ID" "RATE_LIMITED" "" "" >> "$SUMMARY"
      return 0
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' "$ID" "$attempt" "$t0" "$(date +%s)" "${status:-crash}" >> "$TIMINGS"
    log "[$ID] rc=$rc status=${status:-нет} session=${session_id:-нет}"

    case "$status" in
      PASS)
        finish_pass "$issue" "$result"; return 0 ;;
      ALREADY_DONE)
        park_worktree "$ID" "already-done"
        move_ticket "$issue" done "preflight: already-done"
        printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$ID" "ALREADY_DONE" "" "" >> "$SUMMARY"
        return 0 ;;
      BLOCKED|NEEDS_HUMAN)
        # Тикет остаётся в in-work/: следующая ночь его соберёт, а человек утром видит,
        # за что брались и не доехали. В backlog/ он был бы неотличим от нетронутого.
        park_worktree "$ID" "$status"
        printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$ID" "$status" "" "$(json_field "$result" summary)" >> "$SUMMARY"
        return 0 ;;
      CONTINUE)
        # Контекст передан намеренно — свежая сессия, а не сбой: без backoff и без resume.
        mode=fresh; session_id=""; resume_streak=0; continue ;;
    esac

    # Два разных сбоя делят эту ветку и требуют противоположных ответов.
    # rc=0 без результата — сессия завершилась ЧИСТО, не сделав работы: на практике она
    # запустила фоновый Workflow и ответила «жду», убив его вместе с собой. Resume повторил
    # бы то же ожидание, поэтому следующая попытка идёт без Workflow (mode=direct).
    # rc!=0 — настоящий сбой или ошибка API: лестница resume → resume → fresh.
    local backoff=$(( 30 * attempt ))
    log "[$ID] результата нет — пауза ${backoff}с"
    sleep "$backoff"
    if [ "$rc" = 0 ] && [ "$mode" != direct ]; then
      log "[$ID] сессия кончилась без результата — перехожу в direct (без Workflow)"
      mode=direct; session_id=""; resume_streak=0
    else
      resume_streak=$((resume_streak+1))
      if [ -n "$session_id" ] && [ "$resume_streak" -le 2 ]; then mode=resume
      else mode=fresh; session_id=""; resume_streak=0; fi
    fi
  done

  park_worktree "$ID" "exhausted"
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$ID" "EXHAUSTED" "" "" >> "$SUMMARY"
  log "[$ID] сдался после $RETRIES попыток"
  return 1
}

# PASS: проверки → коммит → перенос тикета → дозапись результата. Порядок фиксирован:
# атомарным «коммит + перенос» сделать нельзя в принципе, тикет вне git. Умрём между
# шагами — тикет останется в in-work/ при уже сделанном коммите, и preflight следующей
# ночи вернёт already-done. Обратный порядок терял бы работу.
finish_pass() {
  local issue="$1" result="$2" subject hash
  if ! gate_checks; then
    log "[$ID] проверки красные — НЕ коммичу"
    park_worktree "$ID" "red-checks"
    python3 - "$result" <<'PY'
import json, sys
p = sys.argv[1]
try: d = json.load(open(p))
except Exception: d = {}
d["status"] = "BLOCKED"
d.setdefault("blockers", []).insert(0, "проверки перед коммитом красные, работа убрана в git stash")
json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
PY
    printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$ID" "BLOCKED_CHECKS" "" "красные проверки, см. logs/$ID.checks.log" >> "$SUMMARY"
    return 0
  fi
  subject="$(json_field "$result" commitSubject)"
  [ -n "$subject" ] || subject="feat: $PHASE/$ID $(head -1 "$issue" | sed 's/^#\s*//' | cut -c1-60)"
  hash="$(commit_ticket "$ID" "$subject")"
  if [ -z "$hash" ]; then
    log "[$ID] коммитить нечего — считаю already-done"
    move_ticket "$issue" done "PASS без диффа"
    printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$ID" "ALREADY_DONE" "" "PASS, но дифф пустой" >> "$SUMMARY"
    return 0
  fi
  log "[$ID] коммит $hash: $subject"
  move_ticket "$issue" done "PASS, коммит $hash"
  python3 - "$result" "$hash" <<'PY'
import json, sys
p, h = sys.argv[1], sys.argv[2]
try: d = json.load(open(p))
except Exception: d = {}
d["commit"] = h
json.dump(d, open(p, "w"), ensure_ascii=False, indent=1)
PY
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$ID" "PASS" "$hash" "$(json_field "$result" summary)" >> "$SUMMARY"
  # Отчёт петли уже на диске — дорисовываем страницу, чтобы в ней были коммит и времена.
  [ -f "$ROOT/.claude/loop-reports/$ID.json" ] && \
    node "$ROOT/bashs/night-report.js" ticket "$ID" >>"$LOGF" 2>&1
  return 0
}

log "watcher: ${#ISSUES[@]} тикетов, по одному, попыток=$RETRIES, модель=$MODEL, бюджет=\$$BUDGET"
rm -f "$W/dirty.stop"
for issue in "${ISSUES[@]}"; do
  case "$issue" in /*) ;; *) issue="$ROOT/$issue" ;; esac
  [ -f "$issue" ] || { log "пропуск (не файл): $issue"; continue; }
  run_issue "$issue"
done

log "watcher закончил. сводка:"; column -t -s $'\t' "$SUMMARY" 2>/dev/null || cat "$SUMMARY"
grep -q $'\tEXHAUSTED\t' "$SUMMARY" && exit 1
exit 0
