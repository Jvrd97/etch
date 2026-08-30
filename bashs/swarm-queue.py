#!/usr/bin/env python3
# [review:need-review] PHASE-03/swarm-queue
# summary: очередь тикетов без владельца — тикеты лежат общим списком, дорожка берёт
#          следующий сама, лок не даёт двоим взять один.
#
# ЗАЧЕМ. Сейчас рой раздаёт тикеты по дорожкам заранее (индекс % 4). Дорожка, которой
# достался L, работает 40 минут; соседняя с двумя S освобождается через 20 и стоит.
# Простой встроен в конструкцию: волна кончается по самому длинному тикету. Очередь без
# владельца это чинит — свободная дорожка берёт следующий тикет сама.
#
# ЧТО ЭТО НЕ. Не планировщик и не демон: ни одного фонового процесса, ни сети, ни базы.
# Одна команда на действие, всё состояние — один JSONL-файл.
#
# ФОРМАТ. Одна строка queue.jsonl = один переход состояния. Текущее состояние тикета —
# свёртка last-wins по id: проход по всем строкам, последняя строка по id побеждает.
# Переход = дописывание {**прошлая строка, ts, status, ...}, поэтому история переходов
# остаётся в файле целиком, а состояние считается за один проход.
#   status: ready | taken | done | failed | stuck
#     ready   свободен, можно брать
#     taken   взят дорожкой: lane, pid, host, worktree, takenAt, lease
#     done    закрыт с зелёными проверками
#     failed  BLOCKED / NEEDS_HUMAN / исчерпан maxRounds — в очередь НЕ возвращается
#     stuck   владелец умер и оставил грязное дерево — только человеку
#
# ЛОК. Механика та же, что у claim в alv/bashs/swarm_bus.py, и по той же причине:
# одного O_APPEND мало. Между «прочитал, что тикет ready» и «дописал строку захвата»
# успевает влезть сосед, и тикет возьмут двое. Поэтому вся последовательность
# «прочитал файл → свернул в состояния → проверил статус → дописал строку» целиком
# идёт под fcntl.flock(LOCK_EX) на ОТДЕЛЬНОМ файле queue.lock:
#   - лок стоит не на queue.jsonl, чтобы читатели (status) не ждали писателей;
#   - flock блокирующий: второй процесс не получает ошибку, он честно ждёт очереди;
#   - снимается в finally, а сверх того ядро снимает его при закрытии файла и при смерти
#     процесса — упавшая дорожка очередь не подвешивает;
#   - лок РЕКОМЕНДАТЕЛЬНЫЙ: он работает ровно потому, что все писатели идут через эту
#     команду. Правка queue.jsonl редактором его не заметит;
#   - fcntl.flock — POSIX и локальная ФС. На сетевом диске (NFS, iCloud Drive) гарантий нет;
#   - лок не переиспользуемый: вложенный вызов в одном процессе даст самоблокировку,
#     поэтому все команды берут его РОВНО ОДИН раз, на верхнем уровне.
#
# АРЕНДА. Упавший владелец в alv блокировал задачу навсегда: ни аренды, ни heartbeat,
# ни возврата в open. Здесь у захвата есть срок (--lease-sec, по умолчанию 45 минут) и
# записаны pid, host и worktree. Просроченный или мёртвый захват отбирается — автоматически
# на каждом next, и вручную командой reap. Куда возвращать, решает состояние worktree:
# чистое — тикет уходит обратно в ready, грязное — в stuck, человеку. Автоматически чистить
# чужой worktree нельзя, там может лежать час работы.
#
# ГДЕ ЛЕЖИТ. <главное рабочее дерево>/.night/swarm/queue.jsonl (см. шапку swarm-board.py:
# .night/ уже в .gitignore, в worktree дорожки этого каталога нет и быть не может).

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import socket
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

QUEUE_FILENAME = "queue.jsonl"
LOCK_FILENAME = "queue.lock"
DEFAULT_LEASE = 2700          # 45 минут: тикет размера L закрывается за 40
DEFAULT_MAX_ATTEMPTS = 3
EST_ORDER = {"S": 0, "M": 1, "L": 2, "XL": 3, "": 4}
SCOPE = "habit-tracker"

EXIT_OK = 0
EXIT_NOT_OWNER = 1
EXIT_ERROR = 2
EXIT_NOTHING = 3      # брать нечего — нормальный исход для скрипта, не сбой


# --- где лежит состояние (то же правило, что в swarm-board.py) -------------------

def repo_root(explicit: str = "") -> str:
    if explicit:
        return os.path.abspath(explicit)
    env = os.environ.get("SWARM_ROOT", "").strip()
    if env:
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=here, capture_output=True, text=True, timeout=10,
        )
        common = out.stdout.strip()
        if out.returncode == 0 and common:
            root = os.path.dirname(os.path.abspath(os.path.join(here, common)))
            if root and os.path.isdir(root):
                return root
    except Exception:
        pass
    return os.path.dirname(here)


def state_dir(root: str, explicit: str = "") -> str:
    if explicit:
        return os.path.abspath(explicit)
    env = os.environ.get("SWARM_STATE_DIR", "").strip()
    if env:
        return os.path.abspath(env)
    return os.path.join(root, ".night", "swarm")


def queue_path(sdir: str) -> str:
    return os.path.join(sdir, QUEUE_FILENAME)


# --- чтение, запись, лок ---------------------------------------------------------

def read_rows(path: str) -> list:
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("id"):
                    rows.append(row)
    except OSError:
        return []
    return rows


def append_rows(sdir: str, rows: list) -> None:
    # Одна строка вместо списка — тихая потеря перехода: словарь итерируется по ключам,
    # в файл уезжают "ts", "id", ... и терпимый парсер молча их пропускает. Поймано на
    # первом же прогоне гонки, когда четыре дорожки получили один и тот же тикет.
    if isinstance(rows, dict):
        rows = [rows]
    if not rows:
        return
    os.makedirs(sdir, exist_ok=True)
    with open(queue_path(sdir), "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()


@contextmanager
def queue_lock(sdir: str):
    os.makedirs(sdir, exist_ok=True)
    path = os.path.join(sdir, LOCK_FILENAME)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def states(sdir: str) -> dict:
    """Свёртка last-wins: словарь id → текущая строка."""
    cur = {}
    for row in read_rows(queue_path(sdir)):
        cur[str(row["id"])] = row
    return cur


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def age_sec(ts: str) -> float:
    try:
        then = datetime.fromisoformat(str(ts))
    except ValueError:
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds()


def pid_alive(pid, host: str) -> bool:
    """Живость владельца. Неизвестен pid или чужой хост — считаем живым и ждём аренду.

    Своего pid команда НЕ подставляет намеренно: `swarm-queue.py next` живёт полсекунды
    и умирает сразу после захвата, а Bash-вызов агента — свой короткий shell. Записать
    такой pid значит объявить каждый захват брошенным через секунду (поймано на прогоне).
    Настоящий pid знает только драйвер дорожки, он и передаёт его флагом --pid $$.
    Без него единственный сторож — аренда, и это честно.
    """
    if pid in (None, "", 0):
        return True
    if host and host != socket.gethostname():
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def worktree_dirty(worktree: str) -> bool:
    if not worktree or not os.path.isdir(worktree):
        return False
    try:
        out = subprocess.run(
            ["git", "-C", worktree, "status", "--porcelain", "--", SCOPE],
            capture_output=True, text=True, timeout=30,
        )
        return bool(out.stdout.strip())
    except Exception:
        return True      # не смогли проверить — считаем грязным, отдаём человеку


# --- разбор тикета ---------------------------------------------------------------

def parse_ticket(path: str) -> dict:
    """id, оценка, заголовок и блокеры одного .md. Frontmatter в этом репозитории нет.

    Правила разбора блокеров те же, что в night-collect.py: вырезать содержимое обратных
    кавычек, отрезать прозу по первому тире или точке, выбросить токены со слэшем.
    """
    name = os.path.basename(path)
    m = re.match(r"^(\d+)-", name)
    tid = m.group(1) if m else os.path.splitext(name)[0]
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {"id": tid, "path": os.path.abspath(path), "est": "", "title": "", "deps": []}

    h1 = re.search(r"^#\s+(.+)$", text, re.M)
    title = h1.group(1).strip() if h1 else ""

    est = ""
    fe = re.search(r"^(?:- )?\*\*Estimated\*\*:\s*(.*)$", text, re.M | re.I)
    if fe:
        me = re.match(r"\s*([A-Za-z]{1,2})\b", fe.group(1))
        est = me.group(1).upper() if me else ""

    deps = []
    fb = re.search(r"^(?:- )?\*\*Blocked by\*\*:\s*(.*)$", text, re.M | re.I)
    if fb and fb.group(1).strip().lower() not in {"none", "нет", "-", "—", "n/a", ""}:
        s = re.sub(r"`[^`]*`", " ", fb.group(1))
        s = re.split(r"[—–;]|\.\s", s, maxsplit=1)[0]
        for tok in re.split(r"[\s,\[\]]+", s):
            if not tok or "/" in tok:
                continue
            mt = re.fullmatch(r"#?(\d{1,4})", tok)
            if not mt:
                continue
            num = mt.group(1).lstrip("0") or "0"
            if num != tid and num not in deps:
                deps.append(num)

    return {"id": tid, "path": os.path.abspath(path), "est": est, "title": title, "deps": deps}


def collect(root: str, phase: str, limit: int, skip: str, results_dir: str) -> list:
    """Отбор тикетов тем же кодом, которым его делает ночной прогон.

    Свой второй отбор здесь заводить нельзя: два расходящихся фильтра — это тикет
    с пометкой «НЕ БРАТЬ», собранный в автономный прогон. night-collect.py вызывается
    подпроцессом, а не копируется.
    """
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "night-collect.py")
    if not os.path.isfile(script):
        print("нет {}: нечем отбирать тикеты".format(script), file=sys.stderr)
        return []
    cmd = [sys.executable, script, "--root", root, "--phase", phase, "--max", str(limit)]
    if skip:
        cmd += ["--skip", skip]
    if results_dir:
        cmd += ["--results-dir", results_dir]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        print(out.stderr.strip(), file=sys.stderr)
        return []
    paths = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip():
            paths.append(parts[0].strip())
    return paths


# --- отзыв брошенных захватов ----------------------------------------------------

def reclaim(cur: dict, lease_sec: int, max_attempts: int, force: bool = False) -> list:
    """Строки-возвраты для захватов, чей владелец мёртв или чья аренда просрочена.

    Вызывается ПОД ЛОКОМ — и из next, и из reap. Автоматический вызов внутри next
    важнее ручного: команду reap никто не позовёт, а next зовут все и постоянно.
    """
    out = []
    for row in cur.values():
        if row.get("status") != "taken":
            continue
        alive = pid_alive(row.get("pid"), str(row.get("host", "")))
        # Срок аренды — тот, о котором договорились при захвате: дорожка рассчитывала
        # именно на него. Флаг --force у reap отбирает это право у строки и отдаёт человеку.
        limit = lease_sec if force else (row.get("lease") or lease_sec)
        overdue = age_sec(row.get("takenAt") or row.get("ts", "")) > limit
        if alive and not overdue:
            continue
        why = "владелец мёртв" if not alive else "аренда просрочена"
        attempts = int(row.get("attempts") or 1)
        dirty = worktree_dirty(str(row.get("worktree", "")))
        if dirty or attempts >= max_attempts:
            reason = "{}, дерево {} грязное — руками".format(why, row.get("worktree", "?")) if dirty \
                else "{}, попыток {} — руками".format(why, attempts)
            out.append({**row, "ts": now_iso(), "status": "stuck", "reason": reason})
        else:
            out.append({**row, "ts": now_iso(), "status": "ready", "lane": None, "pid": None,
                        "host": None, "worktree": None, "takenAt": None, "pinned": None,
                        "attempts": attempts, "reason": "{} ({}), дерево чистое — вернул в очередь"
                                                        .format(why, row.get("lane", "?"))})
    return out


def dep_block(cur: dict, row: dict, lane: str, cross_lane: str) -> str:
    """Почему тикет брать нельзя из-за блокеров. Пусто — можно.

    Зависимости в рое честнее, чем в ночном прогоне: тикет, чей блокер закрыт на СОСЕДНЕЙ
    ветке, брать нельзя — кода блокера в дереве дорожки нет, и петля напишет его заново.
    Снимается это слиянием веток и командой merged, а не флагом.
    """
    for dep in row.get("deps") or []:
        d = cur.get(str(dep))
        if d is None:
            continue                        # блокера нет в очереди: он закрыт до прогона
        if d.get("status") != "done":
            return "блокер #{} ещё не закрыт".format(dep)
        if d.get("merged"):
            continue
        if d.get("lane") and d.get("lane") != lane and cross_lane == "block":
            return "блокер #{} закрыт на ветке {} — в твоём дереве его кода нет".format(dep, d["lane"])
    return ""


# --- команды ---------------------------------------------------------------------

def cmd_fill(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    sdir = state_dir(root, args.state_dir)

    paths = list(args.paths)
    if args.tsv:
        src = sys.stdin if args.tsv == "-" else open(args.tsv, encoding="utf-8")
        for line in src:
            first = line.split("\t")[0].strip()
            if first:
                paths.append(first)
        if src is not sys.stdin:
            src.close()
    if args.collect:
        paths += collect(root, args.phase, args.max, args.skip, args.results_dir)
    if not paths:
        print("нечего заливать: ни путей, ни --tsv, ни --collect", file=sys.stderr)
        return EXIT_ERROR

    with queue_lock(sdir):
        if args.reset:
            path = queue_path(sdir)
            if os.path.isfile(path):
                stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
                os.rename(path, os.path.join(sdir, "queue.{}.jsonl".format(stamp)))
                print("прошлая очередь убрана в queue.{}.jsonl".format(stamp))
        cur = states(sdir)
        new = []
        for p in paths:
            full = os.path.abspath(os.path.join(root, p)) if not os.path.isabs(p) else p
            if not os.path.isfile(full):
                print("нет файла, пропускаю: {}".format(full), file=sys.stderr)
                continue
            t = parse_ticket(full)
            if t["id"] in cur and not args.force:
                continue                    # заливка идемпотентна: повторный fill не сбивает захваты
            new.append({"ts": now_iso(), "id": t["id"], "path": t["path"], "est": t["est"],
                        "title": t["title"], "deps": t["deps"], "status": "ready",
                        "lane": None, "pid": None, "host": None, "worktree": None,
                        "takenAt": None, "lease": None, "pinned": None, "attempts": 0,
                        "merged": False, "reason": ""})
        append_rows(sdir, new)

    for row in new:
        print("+ #{}\t{}\t{}".format(row["id"], row["est"] or "?", row["title"] or row["path"]))
    print("залито {} тикетов, всего в очереди {}".format(len(new), len(states(sdir))))
    return EXIT_OK


def cmd_next(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    sdir = state_dir(root, args.state_dir)
    worktree = os.path.abspath(args.worktree) if args.worktree else os.getcwd()
    limit_est = EST_ORDER.get((args.max_size or "").upper(), 9)

    taken = None
    reason = ""
    with queue_lock(sdir):
        cur = states(sdir)
        back = reclaim(cur, args.lease_sec, args.max_attempts)
        if back:
            append_rows(sdir, back)
            for row in back:
                cur[str(row["id"])] = row

        free, blocked = [], []
        for row in cur.values():
            if row.get("status") != "ready":
                continue
            if row.get("pinned") and row["pinned"] != args.lane:
                blocked.append("#{} закреплён за {}".format(row["id"], row["pinned"]))
                continue
            if EST_ORDER.get(row.get("est") or "", 4) > limit_est:
                blocked.append("#{} крупнее {}".format(row["id"], args.max_size))
                continue
            why = dep_block(cur, row, args.lane, args.cross_lane_deps)
            if why:
                blocked.append("#{}: {}".format(row["id"], why))
                continue
            free.append(row)

        if free:
            # Короткие вперёд: дорожка, добравшая S в хвосте волны, простаивает меньше,
            # чем дорожка, взявшая L последней. Кому нужен обратный порядок (пока свободны
            # все четыре дорожки, длинные выгоднее ставить первыми) — флаг --order long.
            rev = args.order == "long"
            free.sort(key=lambda r: (-EST_ORDER.get(r.get("est") or "", 4) if rev
                                     else EST_ORDER.get(r.get("est") or "", 4),
                                     int(r.get("attempts") or 0), int(r["id"])))
            row = free[0]
            taken = {**row, "ts": now_iso(), "status": "taken", "lane": args.lane,
                     "pid": int(args.pid) if args.pid else None,
                     "host": socket.gethostname(), "worktree": worktree,
                     "takenAt": now_iso(), "lease": args.lease_sec,
                     "attempts": int(row.get("attempts") or 0) + 1, "pinned": None, "reason": ""}
            append_rows(sdir, [taken])
        else:
            waiting = [r for r in cur.values() if r.get("status") == "taken"]
            if blocked:
                reason = "свободных нет: " + "; ".join(blocked[:4])
            elif waiting:
                reason = "все оставшиеся тикеты в работе у других дорожек"
            else:
                reason = "очередь пуста"

    if args.json:
        print(json.dumps({"ticket": taken, "reason": reason}, ensure_ascii=False))
    elif taken:
        print("{}\t{}\t{}\t{}".format(taken["path"], taken["id"], taken["est"] or "", taken["title"] or ""))
    if not taken:
        if not args.json:
            print(reason, file=sys.stderr)
        return EXIT_NOTHING
    return EXIT_OK


def _close(args: argparse.Namespace, status: str, extra: dict) -> int:
    sdir = state_dir(repo_root(args.root), args.state_dir)
    tid = str(args.id).lstrip("#")
    with queue_lock(sdir):
        cur = states(sdir)
        row = cur.get(tid)
        if row is None:
            print("нет такого тикета в очереди: #{}".format(tid), file=sys.stderr)
            return EXIT_ERROR
        # Владение здесь — не только соглашение: закрыть чужой тикет значит стереть чужой
        # захват и отдать соседу дерево, которого он не видит.
        if row.get("lane") and args.lane and row["lane"] != args.lane and not args.force:
            print("тикет #{} держит {}, а не {} (--force, если правда надо)"
                  .format(tid, row["lane"], args.lane), file=sys.stderr)
            return EXIT_NOT_OWNER
        new = {**row, "ts": now_iso(), "status": status, **extra}
        append_rows(sdir, [new])
    print("#{} → {}{}".format(tid, status, " ({})".format(new.get("reason")) if new.get("reason") else ""))
    return EXIT_OK


def cmd_done(args: argparse.Namespace) -> int:
    return _close(args, "done", {"commit": args.commit, "reason": args.note,
                                 "finishedAt": now_iso(), "pinned": None})


def cmd_fail(args: argparse.Namespace) -> int:
    if args.requeue:
        # CONTINUE, переполнение контекста, обрыв API: работа наполовину сделана и лежит
        # в worktree ЭТОЙ дорожки вместе с handoff-конспектом. Отдать такой тикет соседу
        # значит отдать ему чужое грязное дерево, которого он не видит, — поэтому pinned.
        return _close(args, "ready", {"reason": args.reason, "pinned": args.lane,
                                      "lane": None, "pid": None, "host": None,
                                      "worktree": None, "takenAt": None})
    if args.stuck:
        return _close(args, "stuck", {"reason": args.reason})
    # BLOCKED, красные проверки, исчерпан maxRounds: в очередь НЕ возвращается. Повтор
    # другой дорожкой упрётся в ту же стену и сожжёт агента впустую.
    return _close(args, "failed", {"reason": args.reason, "finishedAt": now_iso(), "pinned": None})


def cmd_reap(args: argparse.Namespace) -> int:
    sdir = state_dir(repo_root(args.root), args.state_dir)
    with queue_lock(sdir):
        cur = states(sdir)
        back = reclaim(cur, args.lease_sec, args.max_attempts, args.force)
        append_rows(sdir, back)
    for row in back:
        print("#{} → {}: {}".format(row["id"], row["status"], row.get("reason", "")))
    if not back:
        print("брошенных захватов нет")
    return EXIT_OK


def cmd_merged(args: argparse.Namespace) -> int:
    """Отметить закрытые тикеты как слитые в общую основу.

    Пока ветки fast-* не слиты, тикет, чей блокер закрыт на соседней ветке, брать нельзя.
    Эта команда — то, что вызывается ПОСЛЕ слияния веток и перебазирования worktree.
    Ради этого волны в рое и остаются: не как способ раздачи, а как точки слияния.
    """
    sdir = state_dir(repo_root(args.root), args.state_dir)
    ids = {s.strip().lstrip("#") for s in (args.id or "").split(",") if s.strip()}
    with queue_lock(sdir):
        cur = states(sdir)
        rows = []
        for tid, row in sorted(cur.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
            if row.get("status") != "done" or row.get("merged"):
                continue
            if ids and tid not in ids:
                continue
            rows.append({**row, "ts": now_iso(), "merged": True})
        append_rows(sdir, rows)
    for row in rows:
        print("#{} слит в общую основу".format(row["id"]))
    if not rows:
        print("нечего отмечать: незакрытых слияний нет")
    return EXIT_OK


def cmd_status(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    sdir = state_dir(root, args.state_dir)
    cur = states(sdir)
    if args.json:
        print(json.dumps(sorted(cur.values(), key=lambda r: int(r["id"]) if str(r["id"]).isdigit() else 0),
                         ensure_ascii=False, indent=2))
        return EXIT_OK
    if not cur:
        print("очередь пуста: {}".format(queue_path(sdir)))
        return EXIT_OK
    order = {"taken": 0, "ready": 1, "stuck": 2, "failed": 3, "done": 4}
    rows = sorted(cur.values(), key=lambda r: (order.get(r.get("status"), 9),
                                               int(r["id"]) if str(r["id"]).isdigit() else 0))
    for row in rows:
        who = row.get("lane") or row.get("pinned") or ""
        if row.get("status") == "taken":
            who += " {:.0f}м".format(age_sec(row.get("takenAt") or row["ts"]) / 60)
        if row.get("status") == "done" and row.get("commit"):
            who = (who + " " + str(row["commit"])).strip()
        if row.get("merged"):
            who += " ⤳merged"
        print("{:<7} #{:<5} {:<2} {:<12} {}".format(
            row.get("status", "?"), row["id"], row.get("est") or "?", who.strip(),
            (row.get("title") or "")[:60]))
        if row.get("reason"):
            print("        └ {}".format(row["reason"]))
    counts = {}
    for row in rows:
        counts[row.get("status", "?")] = counts.get(row.get("status", "?"), 0) + 1
    print("— " + ", ".join("{}: {}".format(k, v) for k, v in sorted(counts.items())))
    print("— " + queue_path(sdir))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="swarm-queue.py",
        description="Очередь тикетов без владельца: дорожка берёт следующий сама.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="коды возврата: 0 — сделано, 1 — тикет держит другая дорожка,\n"
               "                2 — ошибка, 3 — брать нечего (нормальный исход, не сбой)",
    )
    ap.add_argument("--root", default="")
    ap.add_argument("--state-dir", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)

    fill = sub.add_parser("fill", help="залить тикеты в очередь (идемпотентно)")
    fill.add_argument("paths", nargs="*", help="пути к .md тикетов")
    fill.add_argument("--tsv", default="", help="файл или '-': первая колонка — путь (вывод night-collect.py)")
    fill.add_argument("--collect", action="store_true", help="отобрать тикеты через bashs/night-collect.py")
    fill.add_argument("--phase", default="PHASE-03")
    fill.add_argument("--max", type=int, default=12)
    fill.add_argument("--skip", default="")
    fill.add_argument("--results-dir", default="")
    fill.add_argument("--reset", action="store_true", help="убрать прошлую очередь в архив и начать чистую")
    fill.add_argument("--force", action="store_true", help="перезалить тикет, который уже в очереди")
    fill.set_defaults(func=cmd_fill)

    nxt = sub.add_parser("next", help="взять следующий тикет (атомарно)")
    nxt.add_argument("--lane", required=True)
    nxt.add_argument("--worktree", default="", help="рабочее дерево дорожки (по умолчанию cwd)")
    nxt.add_argument("--max-size", default="", choices=["", "S", "M", "L", "XL"],
                     help="не брать тикеты крупнее: для хвоста прогона")
    nxt.add_argument("--order", default="short", choices=["short", "long"],
                     help="short — S раньше L (по умолчанию); long — наоборот")
    nxt.add_argument("--lease-sec", type=int, default=DEFAULT_LEASE)
    nxt.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    nxt.add_argument("--cross-lane-deps", default="block", choices=["block", "allow"],
                     help="брать ли тикет, чей блокер закрыт на чужой ветке")
    nxt.add_argument("--pid", default="", help="pid драйвера дорожки ($$); без него сторож один — аренда")
    nxt.add_argument("--json", action="store_true")
    nxt.set_defaults(func=cmd_next)

    done = sub.add_parser("done", help="закрыть тикет зелёным")
    done.add_argument("--lane", required=True)
    done.add_argument("--id", required=True)
    done.add_argument("--commit", default="")
    done.add_argument("--note", default="")
    done.add_argument("--force", action="store_true")
    done.set_defaults(func=cmd_done)

    fail = sub.add_parser("fail", help="тикет не закрыт: вернуть или пометить")
    fail.add_argument("--lane", required=True)
    fail.add_argument("--id", required=True)
    fail.add_argument("--reason", required=True)
    fail.add_argument("--requeue", action="store_true",
                      help="CONTINUE/обрыв API: вернуть в очередь, закрепив за этой же дорожкой")
    fail.add_argument("--stuck", action="store_true", help="нужен человек, дерево трогать нельзя")
    fail.add_argument("--force", action="store_true")
    fail.set_defaults(func=cmd_fail)

    reap = sub.add_parser("reap", help="отобрать брошенные захваты (то же делает next сам)")
    reap.add_argument("--lease-sec", type=int, default=DEFAULT_LEASE)
    reap.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    reap.add_argument("--force", action="store_true",
                      help="мерить --lease-sec, а не срок, записанный при захвате")
    reap.set_defaults(func=cmd_reap)

    merged = sub.add_parser("merged", help="после слияния веток: снять запрет на зависимые тикеты")
    merged.add_argument("--id", default="", help="номера через запятую; пусто — все закрытые")
    merged.set_defaults(func=cmd_merged)

    st = sub.add_parser("status", help="что взято, что свободно, кем")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_status)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
