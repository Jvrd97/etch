#!/usr/bin/env bash
# [review:need-review] PHASE-03/night-run
# summary: ночной прогон одной командой — собрать исполнимые без человека тикеты в список,
#          прогнать их по одному через issue-watcher.sh (headless-сессия claude на тикет),
#          утром провести ревью по коммитам ночи и собрать сводку.
#
# Запуск:
#   bashs/issue-night.sh collect [-n MAX] [-x 155,159] [--all]      # только список, ничего не запускать
#   bashs/issue-night.sh run     [-n MAX] [-x ...] [--ask-perms] [--no-review] [-r N] [-b USD]
#   bashs/issue-night.sh review  [SINCE_REF]                        # только утреннее ревью
#
#   -n MAX       потолок тикетов за волну (по умолчанию 6)
#   -x 155,159   снять конкретные номера
#   --all        без потолка (корректность-фильтры остаются: не-AFK и незакрытые блокеры
#                берутся всегда, иначе работа встанет на отсутствующем основании)
#   -j N         принимается только 1 (см. ниже, «одно рабочее дерево»)
#   --ask-perms  не отключать проверку прав (по умолчанию отключена, см. watcher)
#   --no-review  не проводить утреннее ревью в конце
#   --keep-native      не отсеивать тикеты со слоем Mac/iOS
#   --keep-committed   не отсеивать тикеты, чей номер уже в истории ветки
#
# Отличия от alv-версии, которые видны прямо здесь:
#   * ОДНО РАБОЧЕЕ ДЕРЕВО. Worktree в этом проекте сняты намеренно (мало места на диске),
#     поэтому все тикеты идут строго по одному. Параллельности -j 5 и локов по сервису нет:
#     сервисов нет вовсе, тикеты вертикальные, у всех один скоуп habit-tracker/.
#   * СОСТОЯНИЕ В .night/. У alv оно в .dsh/watcher/. Здесь каталога .dsh/ нет, .claude/
#     лежит в git (состояние прогона утекло бы в коммиты), а issues/ первой строкой в
#     .gitignore и переживает не каждый день. .night/ в корне — одна строка в .gitignore,
#     видно человеку сразу, ничего чужого не задевает.
#   * ОТЧЁТЫ В MARKDOWN. docs-html/, doc-граф и сервер 8931 сюда не переносились —
#     см. bashs/night-report.js и .claude/skills/night-run/SKILL.md.

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

PHASE="PHASE-03"
BRANCH_EXPECTED="phase-03"
SCOPE="habit-tracker"
W="$ROOT/.night"
DATE="$(date +%F)"
LIST="$W/night-$DATE.list"
DROPPED="$W/night-$DATE.dropped.tsv"
START_REF_FILE="$W/night-$DATE.start"
REPORTER="$ROOT/bashs/night-report.js"

CMD="${1:-}"; shift || true
MAX=6; SKIP=""; REVIEW=1; SINCE=""; EXTRA=(); COLLECT_EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    -n) MAX="$2"; shift 2 ;;
    -x) SKIP="$2"; shift 2 ;;
    --all) MAX=100000; shift ;;
    -r) EXTRA+=(-r "$2"); shift 2 ;;
    -b) EXTRA+=(-b "$2"); shift 2 ;;
    -j) [ "$2" = 1 ] || { echo "-j принимает только 1: worktree нет, рабочее дерево одно,"; \
         echo "две петли в habit-tracker/ перетопчут друг другу файлы, тесты и git add."; exit 1; }
        shift 2 ;;
    --ask-perms) EXTRA+=(--ask-perms); shift ;;
    --no-review) REVIEW=0; shift ;;
    --keep-native) COLLECT_EXTRA+=(--allow-native); shift ;;
    --keep-committed) COLLECT_EXTRA+=(--allow-committed); shift ;;
    *) SINCE="$1"; shift ;;
  esac
done

mkdir -p "$W" "$W/results" "$W/handoff" "$W/logs" "$W/live" "$W/reviews"

# --- предусловия ---------------------------------------------------------------
# Ночь, начатая на грязном дереве или в no-code день, не падает честно: она выдаёт
# ночь из BLOCKED и перемешанный дифф. Дешевле не начинать.

nocode_day() {  # $1 = YYYY-MM-DD; 0 = день без кода
  local cfg="$HOME/.claude/nocode/config" d="$1" wd ov days
  [ -f "$cfg" ] || return 1
  wd="$(date -j -f '%Y-%m-%d' "$d" +%w 2>/dev/null)" || return 1
  ov="$(grep -E '^override=' "$cfg" 2>/dev/null | head -1 | cut -d= -f2-)"
  [ "$ov" = "$d:on" ] && return 0
  [ "$ov" = "$d:off" ] && return 1
  days="$(grep -E '^days=' "$cfg" 2>/dev/null | head -1 | cut -d= -f2-)"
  case ",$days," in *",$wd,"*) return 0 ;; esac
  return 1
}

preflight_run() {
  local fail=0 branch dirty tomorrow
  command -v claude >/dev/null 2>&1 || { echo "нет claude в PATH"; fail=1; }
  command -v node   >/dev/null 2>&1 || { echo "нет node в PATH — сводку собирать нечем"; fail=1; }
  command -v python3 >/dev/null 2>&1 || { echo "нет python3 в PATH — отбор считать нечем"; fail=1; }

  branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
  [ "$branch" = "$BRANCH_EXPECTED" ] || {
    echo "ветка $branch, а ночь коммитит в $BRANCH_EXPECTED"; fail=1; }

  dirty="$(git -C "$ROOT" status --porcelain -- "$SCOPE")"
  [ -z "$dirty" ] || {
    echo "рабочее дерево $SCOPE/ грязное — утренний дифф смешает чужую работу со своей:"
    printf '%s\n' "$dirty" | head -10; fail=1; }

  # Прогон, стартующий вечером, живёт до утра. Хук nocode-guard считает режим на КАЖДЫЙ
  # вызов Write/Edit/Bash, поэтому переход через полночь во вторник или четверг убивает
  # работу молча: в /.claude/ писать можно, в habit-tracker/ уже нет.
  tomorrow="$(date -v+1d +%F 2>/dev/null || date -d '+1 day' +%F)"
  nocode_day "$DATE"     && { echo "сегодня ($DATE) no-code день — код пишет человек"; fail=1; }
  nocode_day "$tomorrow" && { echo "завтра ($tomorrow) no-code день — прогон умрёт после полуночи"; fail=1; }

  return $fail
}

# --- сбор списка ---------------------------------------------------------------

collect() {
  python3 "$ROOT/bashs/night-collect.py" \
    --root "$ROOT" --phase "$PHASE" --max "$MAX" --skip "$SKIP" \
    --results-dir "$W/results" --dropped-out "$DROPPED" \
    "${COLLECT_EXTRA[@]+"${COLLECT_EXTRA[@]}"}" > "$W/night-$DATE.tsv" || return 1
  cut -f1 "$W/night-$DATE.tsv" > "$LIST"
  local n; n="$(wc -l < "$LIST" | tr -d ' ')"
  echo "collected $n issues → $LIST"
  awk -F'\t' -v r="$ROOT/" '{p=$1; sub(r,"",p); printf "  %-4s %-2s %s\n", $2, $3, p}' "$W/night-$DATE.tsv"
  echo "  отсеяно: $(wc -l < "$DROPPED" | tr -d ' ') (см. $DROPPED)"
}

# Тикет уезжает в in-work/ ДО запуска сессии: иначе повторный collect следующей волны
# соберёт его заново. issues/ в .gitignore — это обычный mv, не git mv, и он никуда не
# коммитится; единственный след переноса, который переживёт `rm -rf issues/`, — журнал
# moves.tsv и сводка ночи в docs/.
move_to_inwork() {
  local f rel dest
  : > "$LIST.next"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    rel="${f#$ROOT/}"; dest="$(printf '%s' "$rel" | sed "s|/backlog/|/in-work/|")"
    if [ "$rel" != "$dest" ] && [ -f "$f" ]; then
      mkdir -p "$(dirname "$ROOT/$dest")"
      mv "$f" "$ROOT/$dest" && \
        printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$(basename "$dest" .md | cut -d- -f1)" \
          "backlog" "in-work" "взят в волну" >> "$W/moves.tsv"
    fi
    echo "$ROOT/$dest" >> "$LIST.next"
  done < "$LIST"
  mv "$LIST.next" "$LIST"
}

# --- утреннее ревью -------------------------------------------------------------
# Сессия свежая и одна на все тикеты. Свежая намеренно: ночные сессии не должны судить
# сами себя. Скилла code-review в этом репозитории нет (в ~/.claude/skills/ его тоже нет),
# поэтому линзы ревью выписаны в промпте здесь, а не позваны по имени.

review() {
  local since="${1:-}"
  [ -n "$since" ] || since="$(cat "$START_REF_FILE" 2>/dev/null || echo 'HEAD~10')"
  local range="$since..HEAD"
  local outdir="docs/$PHASE/night-run/$DATE"
  mkdir -p "$W/reviews"

  node "$REPORTER" night --date "$DATE" >/dev/null 2>&1 || true
  local ids; ids="$(node "$REPORTER" list --date "$DATE" 2>/dev/null | tr '\n' ' ')"
  [ -n "${ids// /}" ] || { echo "ревьюить нечего: тикетов за $DATE нет"; return 0; }
  echo "== утреннее ревью $range, тикеты: $ids → $outdir/"

  local perm=(--dangerously-skip-permissions)
  case " ${EXTRA[*]-} " in *" --ask-perms "*) perm=(--permission-mode acceptEdits) ;; esac

  local t0; t0="$(date +%s)"
  local prompt
  read -r -d '' prompt <<EOF2 || true
Утреннее ревью ночного прогона $DATE. Репо: $ROOT, ветка $BRANCH_EXPECTED, диапазон $range.
ТОЛЬКО ЧТЕНИЕ: код не править, не коммитить, ничего не помечать approved — это делает человек.
Bash-команды по одной, без '&&', без ';', без пайпов. cwd не менять.

Тикеты ночи: $ids

Для КАЖДОГО тикета <id> по порядку:
1. date +%s — это startedAt.
2. Прочитай .claude/loop-reports/<id>.json — там summary, why, файлы, ADR, раунды и
   ЧЕК-ЛИСТ, составленный ночью. Прочитай .night/results/<id>.json — статус и коммит.
   Отчёта нет — работай по результату и по .night/handoff/<id>.md.
3. Есть коммит — прочитай его: git show <commit> --stat, затем git show <commit>.
   Ревьюй ТОЛЬКО этот дифф. Линзы, по порядку:
   a. соответствие тикету: каждый пункт Acceptance закрыт кодом, а не обещанием;
      слои из «Vertical Slice Layers» пройдены все, а не только бэкенд;
   b. корректность: границы суток и таймзоны, идемпотентность, гонки, обработка ошибок,
      пустые и предельные значения, N+1 и лишние запросы;
   c. миграции: ровно одна alembic-голова, downgrade есть и обратим, применённая
      миграция не отредактирована;
   d. контракты: DTO в ответах API, имена событий '<owner>.<entity>.<action>',
      обратная совместимость эндпоинта;
   e. безопасность и приватность: секреты и PII не в логах и не в бандле фронта;
   f. тесты: доказывают поведение из Acceptance, а не факт вызова функции.
   Коммита нет (BLOCKED / NEEDS_HUMAN) — прочитай blockers из results и
   .night/handoff/<id>.md и сформулируй, что именно нужно от человека.
4. Пройди чек-лист из отчёта ПО ПУНКТАМ: каждый пункт → ok | fail | skip и заметка
   с местом, где смотрел (file:line). Текст пункта копируй ДОСЛОВНО из отчёта —
   сводка сшивает результаты с пунктами по строке.
5. Проверь маркер [review:need-review] <id> в тронутых файлах кода (соглашение репо,
   его считает bashs/review-status.sh).
6. date +%s — это finishedAt. diffLines возьми из git show <commit> --shortstat.
7. Запиши .night/reviews/<id>.json строго в форме:
   {"reviewer":"claude -p (opus)","startedAt":"<ISO>","finishedAt":"<ISO>","elapsedSec":<n>,
    "diffLines":<n>,"verdict":"APPROVE|REQUEST_CHANGES|NEEDS_HUMAN",
    "checklist":[{"text":"<дословно из отчёта>","result":"ok|fail|skip","note":"<file:line или причина>"}],
    "findings":[{"file":"<путь>","line":<n>,"severity":"critical|high|medium|low","what":"<что не так>","fix":"<что сделать>"}],
    "humanDecision":"<одной строкой, что нужно от человека, или пусто>"}
8. Выполни: node $REPORTER review <id> $W/reviews/<id>.json

Когда пройдены все тикеты — выполни: node $REPORTER night --date $DATE
Это перерисует $outdir/<id>.md и $outdir/night.md. Файлы сводки не правь руками.
В чат верни одну строку: путь сводки и счётчики APPROVE/REQUEST_CHANGES/NEEDS_HUMAN.
EOF2

  claude -p --output-format text --model "${NIGHT_REVIEW_MODEL:-opus}" \
    --max-budget-usd "${NIGHT_REVIEW_BUDGET:-15}" "${perm[@]}" "$prompt"
  local t1; t1="$(date +%s)"
  echo "== время ревью: $(( t1 - t0 )) c"
  node "$REPORTER" night --date "$DATE" 2>&1 | tail -2
  echo
  bashs/review-status.sh 2>/dev/null | tail -3
}

case "$CMD" in
  collect) collect ;;
  review)  review "$SINCE" ;;
  run)
    preflight_run || { echo "== прогон не начат"; exit 1; }
    # Снимок дерева тикетов до прогона: issues/ вне git, восстановить «что где лежало»
    # после ночи переносов больше нечем.
    ls -R issues/"$PHASE" > "$W/backlog.before-$DATE.txt" 2>/dev/null
    collect
    [ -s "$LIST" ] || { echo "нечего делать"; exit 0; }
    git -C "$ROOT" rev-parse HEAD > "$START_REF_FILE"
    echo "== старт $(date '+%F %T'), HEAD $(cat "$START_REF_FILE")"

    rc=0; wave=0; prev_sig=""
    while [ -s "$LIST" ]; do
      # Волны, а не один проход: тикет, чей блокер только что уехал в done/, становится
      # доступен следующей волне. Останов — когда список повторился: те же тикеты дважды
      # значит остальное ждёт человека, а не нас.
      sig="$(sort "$LIST" | md5 2>/dev/null || sort "$LIST" | md5sum)"
      if [ "$sig" = "$prev_sig" ]; then
        echo "== волна $((wave+1)) повторила бы тот же список — останов"
        break
      fi
      prev_sig="$sig"; wave=$((wave+1))
      move_to_inwork
      echo "== волна $wave: $(wc -l < "$LIST" | tr -d ' ') тикетов, старт $(date '+%F %T')"
      bashs/issue-watcher.sh -f "$LIST" "${EXTRA[@]+"${EXTRA[@]}"}"
      rc=$?
      echo "== волна $wave закончена rc=$rc $(date '+%F %T')"
      if [ -f "$W/ratelimit.stop" ]; then
        echo "== лимит аккаунта исчерпан — следующих волн не будет"
        grep -m1 -h "session limit\|usage limit" "$W"/logs/*.attempt*.json 2>/dev/null |
          python3 -c "import sys,re; s=sys.stdin.read(); m=re.search(r'resets [^\"]+', s); print('==', m.group(0)) if m else None" 2>/dev/null
        break
      fi
      collect
    done
    echo "== watcher закончил rc=$rc после $wave волн(ы) $(date '+%F %T')"
    [ "$REVIEW" = 1 ] && review
    exit $rc ;;
  *) sed -n '2,30p' "$0"; exit 1 ;;
esac
