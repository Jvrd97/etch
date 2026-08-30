#!/usr/bin/env python3
# [review:need-review] PHASE-03/swarm-board
# summary: доска фактов роя — лента коротких записей о том, ЧТО дорожка заняла и что
#          завела в общем дереве habit-tracker/, чтобы три соседние дорожки узнали об
#          этом сейчас, а не при слиянии веток.
#
# ЗАЧЕМ. В alv доска нужна потому, что между сессиями стоит стена — каталог сервиса.
# Здесь стены нет вовсе: тикеты вертикальные, четыре дорожки в четырёх worktree правят
# один и тот же habit-tracker/ и диффа друг друга не видят. Значит две дорожки могут
# завести одну сущность под именами work_interval и time_entry, продублировать хелпер
# в app/core, разойтись в имени поля или повесить две ревизии alembic на одну голову.
# Узнают об этом при слиянии, когда чинить дороже всего.
#
# ЧТО ЭТО НЕ. Не общая память, не координация, не отчёт. Доска несёт ИМЕНА и одну строку
# при каждом; проза, счётчики тестов и разбор приёмки остаются в .claude/loop-reports/<id>.md.
# Дисциплина размера жёсткая (detail и use обрезаны до 300 знаков), потому что доска
# целиком уезжает в промпт каждой фазы петли: доска на 40-60 записей — это 4-6 КБ.
# Пустая доска лучше доски с шумом.
#
# ФОРМАТ. Один JSON-объект в строке board.jsonl, append-only, старые строки не правятся.
# Состояние вычисляется свёрткой last-wins по ключу (дорожка, тикет, вид, имя):
#   state=claim    — «беру это имя», пишется В КОНЦЕ ФАЗЫ ПЛАНА, до первой строки кода;
#   state=fact     — «сделано», пишется в фазе отчёта, уточняет claim настоящими значениями;
#   state=dropped  — «снимаю claim»: тикет упал, вернулся в очередь, имя освободилось.
# Одного «после» не бывает достаточно: тикет размера M закрывается за 20-40 минут, и всё
# это время соседи работают вслепую. Поэтому claim обязателен, а точность в нём не нужна —
# нужно ИМЯ. «Заведу таблицу work_interval, поля уточню» — полезная запись.
#
# ГДЕ ЛЕЖИТ. По умолчанию <главное рабочее дерево>/.night/swarm/board.jsonl.
# Каталог .night/ уже в .gitignore, поэтому состояние роя не попадёт в коммит и ни одной
# строки в .gitignore добавлять не надо; собственного подкаталога рой ни с кем не делит —
# ночной прогон живёт в .night/{results,handoff,logs,live}, рой в .night/swarm/.
# Переопределяется переменной SWARM_STATE_DIR или флагом --state-dir.
# ВАЖНО: путь считается от ГЛАВНОГО рабочего дерева, а не от worktree дорожки. В worktree
# нет ни issues/, ни .night/ (оба в .gitignore, git worktree add их не создаёт), поэтому
# доска физически может быть только одна и только в главном дереве.
#
# ЗАПИСЬ ИЗ ЧЕТЫРЁХ ПРОЦЕССОВ. Одна короткая строка через O_APPEND атомарна для обычного
# файла, и этого хватило бы. Но detail и use — свободный текст от агента, длина строки
# заранее не известна, а цена ошибки — перепутанные записи на доске, которую все читают.
# Поэтому запись идёт под fcntl.flock на отдельном файле board.lock: лок стоит НЕ на самом
# board.jsonl, чтобы читатели (brief, all) не ждали писателей и не зависели от лока вовсе.
# Лок рекомендательный (advisory): он работает ровно потому, что все писатели идут через
# эту команду. Дописывать в board.jsonl редактором нельзя.
#
# ЧИТАТЕЛИ УСТОЙЧИВЫ К МУСОРУ: строка не с '{', битый JSON, оборванный хвост после kill —
# пропускаются молча. Нет файла = пустая доска, а не исключение.

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

BOARD_FILENAME = "board.jsonl"
LOCK_FILENAME = "board.lock"
DEFAULT_LIMIT = 40
DEFAULT_MAX_CHARS = 6000
MAX_NAME = 120
MAX_TEXT = 300
STATES = ("claim", "fact", "dropped")

# Виды фактов под ВЕРТИКАЛЬНЫЕ тикеты. В alv словарь был про сервисы (contract, event,
# schema, gotcha, decision) — здесь сервисной границы нет, зато есть слои одного среза,
# и столкновения случаются именно по слоям.
KINDS = {
    "table": "новая таблица (name = имя таблицы)",
    "column": "колонка в уже существующей таблице (name = таблица.колонка)",
    "migration": "ревизия alembic (name = id ревизии, detail = down_revision=...)",
    "endpoint": "метод и путь (name = 'GET /api/v1/day/{date}')",
    "dto": "схема запроса/ответа: pydantic-модель или тип во frontend",
    "core-fn": "функция или класс, которые соседи обязаны переиспользовать (app/core, app/day, app/crud)",
    "lib-module": "новый модуль общего смысла (app/core/*, app/scheduling/*, frontend/lib/*)",
    "component": "компонент фронта",
    "event": "имя события <owner>.<entity>.<action>",
    "day-rule": "правило дня: канон дня, режимы, границы суток",
    "enum": "набор строковых значений, ставший контрактом",
    "dep": "пакет, добавленный в pyproject.toml или package.json",
    "magnet": "правка файла, который правят почти все (app/main.py, lib/api.ts, conftest.py)",
    "invariant": "запрет или обязанность для тех, кто придёт после (name не нужен, detail обязателен)",
    "debt": "осознанно НЕ сделано — сосед не должен 'чинить' это заодно (detail обязателен)",
    "conflict": "имя оказалось занято: кто уступил и на что перешёл",
}
# Виды, у которых предмет — не имя, а формулировка.
TEXT_KINDS = ("invariant", "debt")


# --- где лежит состояние --------------------------------------------------------

def repo_root(explicit: str = "") -> str:
    """Главное рабочее дерево репозитория, а НЕ worktree дорожки.

    git rev-parse --git-common-dir из worktree печатает .git главного дерева (проверено
    на fast-1), из главного дерева — относительный '../.git', который резолвится от cwd.
    Отсюда одно правило для обоих случаев: abspath(join(cwd, common)) и dirname.
    """
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


def board_path(sdir: str) -> str:
    return os.path.join(sdir, BOARD_FILENAME)


# --- терпимое чтение и атомарная запись -----------------------------------------

def read_rows(path: str) -> list:
    """Все записи файла. Мусор пропускается: отсутствие файла = пустая доска."""
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
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def append_row(sdir: str, row: dict) -> None:
    os.makedirs(sdir, exist_ok=True)
    lock = os.path.join(sdir, LOCK_FILENAME)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with open(lock, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            with open(board_path(sdir), "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    """Дата в UTC — той же шкале, в которой пишется ts.

    В alv --since по умолчанию брал ЛОКАЛЬНУЮ дату, а ts писался в UTC, и записи
    первых двух ночных часов уезжали во «вчера». Здесь обе стороны в UTC.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def clip(raw: str, limit: int) -> str:
    """Схлопнуть пробелы и обрезать. Доска обязана оставаться короткой."""
    text = " ".join((raw or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --- свёртка и отбор ------------------------------------------------------------

def key_of(row: dict) -> tuple:
    return (str(row.get("lane", "")), str(row.get("ticket", "")),
            str(row.get("kind", "")), str(row.get("name", "")))


def fold(rows: list) -> list:
    """Состояние доски: последняя запись по ключу побеждает, dropped убирает ключ.

    Так фаза отчёта уточняет собственный claim настоящими значениями, не заводя вторую
    строку в выдаче, а упавший тикет освобождает занятые имена одной записью dropped.
    Виды invariant/debt/conflict у одной дорожки могут повторяться — у них ключ разводит
    записи полем name, поэтому для них в name кладётся первое слово формулировки.
    """
    seen = {}
    for row in rows:
        seen[key_of(row)] = row
    out = [r for r in seen.values() if r.get("state") != "dropped"]
    out.sort(key=lambda r: str(r.get("ts", "")))
    return out


def matches(row: dict, needle: str) -> bool:
    hay = " ".join(str(row.get(f, "")) for f in ("kind", "name", "detail", "use", "ref")).lower()
    return needle.lower() in hay


def format_row(row: dict) -> str:
    state = row.get("state", "fact")
    lane = row.get("lane", "?")
    ticket = row.get("ticket", "?")
    kind = row.get("kind", "?")
    name = row.get("name", "")
    head = "- [{} {}/#{}] {}".format(state, lane, ticket, kind)
    # У invariant и debt имя — служебный ключ свёртки, вырезанный из начала формулировки;
    # печатать его рядом с самой формулировкой значит сказать одно и то же дважды.
    if name and kind not in TEXT_KINDS:
        head += " " + name
    tail = []
    if row.get("detail"):
        tail.append(str(row["detail"]))
    if row.get("use"):
        tail.append("⇒ " + str(row["use"]))
    if row.get("ref"):
        tail.append(str(row["ref"]))
    return head + (" — " + " | ".join(tail) if tail else "")


# --- команды --------------------------------------------------------------------

def cmd_note(args: argparse.Namespace) -> int:
    sdir = state_dir(repo_root(args.root), args.state_dir)
    name = clip(args.name, MAX_NAME)
    detail = clip(args.detail, MAX_TEXT)
    use = clip(args.use, MAX_TEXT)

    if args.kind in TEXT_KINDS:
        if not detail:
            print("--detail обязателен для вида {}: запрет без формулировки бесполезен".format(args.kind),
                  file=sys.stderr)
            return 2
        if not name:
            # Ключ свёртки должен разводить разные инварианты одной дорожки, иначе второй
            # затрёт первый. Берём первые слова формулировки как имя.
            name = clip(" ".join(detail.split()[:4]), MAX_NAME)
    elif not name:
        print("--name обязателен для вида {}: доска — это имена".format(args.kind), file=sys.stderr)
        return 2

    row = {
        "ts": now_iso(),
        "lane": args.lane,
        "ticket": str(args.ticket).lstrip("#"),
        "state": args.state,
        "kind": args.kind,
        "name": name,
        "detail": detail,
        "use": use,
        "ref": clip(args.ref, MAX_NAME),
    }
    append_row(sdir, row)
    print(format_row(row))
    return 0


def select(args: argparse.Namespace, rows: list, search: str) -> list:
    picked = fold(rows)
    if args.since:
        picked = [r for r in picked if str(r.get("ts", ""))[:10] >= args.since]
    if args.kind:
        wanted = {k.strip() for k in args.kind.split(",") if k.strip()}
        picked = [r for r in picked if r.get("kind") in wanted]
    if args.ticket:
        picked = [r for r in picked if str(r.get("ticket")) == str(args.ticket).lstrip("#")]
    if search:
        # Поиск по предмету идёт по ВСЕМ дорожкам, включая свою: вопрос «занято ли имя»
        # требует полного ответа, и собственный claim в нём тоже уместен.
        picked = [r for r in picked if matches(r, search)]
    elif args.lane and not args.all_lanes:
        # Конспект: своя же запись дорожке не нужна — она её и написала.
        picked = [r for r in picked if r.get("lane") != args.lane]
    return picked[-args.limit:]


def cmd_brief(args: argparse.Namespace) -> int:
    sdir = state_dir(repo_root(args.root), args.state_dir)
    search = (args.like or args.name or "").strip()
    picked = select(args, read_rows(board_path(sdir)), search)

    if not picked:
        if search:
            # В режиме поиска молчание двусмысленно: «не нашёл» и «доска сломалась»
            # выглядят одинаково. Отвечаем прямо.
            print("доска: про «{}» записей нет — имя свободно".format(search))
        # В режиме конспекта не печатаем НИЧЕГО, даже заголовка: этот текст едет
        # в промпт, и пустая доска не должна занимать в нём место.
        return 0

    if search:
        head = "ДОСКА РОЯ, записи про «{}»:".format(search)
    else:
        head = "ЧТО ЗАНЯЛИ И СДЕЛАЛИ СОСЕДНИЕ ДОРОЖКИ (касается тебя):"
    block = "\n".join(format_row(r) for r in picked)
    if len(block) > args.max_chars:
        # Режем по последнему целому переводу строки: обрубленной записи на выходе
        # не бывает — половина имени хуже отсутствия имени.
        block = block[: args.max_chars].rsplit("\n", 1)[0]
    print(head)
    print(block)
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    sdir = state_dir(repo_root(args.root), args.state_dir)
    rows = read_rows(board_path(sdir))
    if args.raw:
        picked = rows
    else:
        picked = select(args, rows, (args.like or args.name or "").strip())
    if args.json:
        print(json.dumps(picked, ensure_ascii=False, indent=2))
        return 0
    if not picked:
        print("доска пуста: {}".format(board_path(sdir)))
        return 0
    for row in picked:
        print(format_row(row))
    print("— {} записей, {}".format(len(picked), board_path(sdir)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    kinds_help = "\n".join("  {:<11} {}".format(k, v) for k, v in KINDS.items())
    ap = argparse.ArgumentParser(
        prog="swarm-board.py",
        description="Доска фактов роя: что дорожка заняла и завела в общем habit-tracker/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="виды фактов (--kind):\n" + kinds_help,
    )
    ap.add_argument("--root", default="", help="корень репозитория (по умолчанию считается сам)")
    ap.add_argument("--state-dir", default="", help="каталог состояния (по умолчанию <root>/.night/swarm)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    note = sub.add_parser("note", help="записать факт на доску")
    note.add_argument("--lane", required=True, help="имя дорожки: fast-1 … fast-4")
    note.add_argument("--ticket", required=True, help="номер тикета, в котором факт появился")
    note.add_argument("--kind", required=True, choices=sorted(KINDS))
    note.add_argument("--state", default="fact", choices=STATES,
                      help="claim — беру имя (фаза плана); fact — сделано (фаза отчёта); dropped — снимаю claim")
    note.add_argument("--name", default="", help="предмет: имя таблицы, путь эндпоинта, сигнатура функции")
    note.add_argument("--detail", default="", help="одна строка, до 300 знаков")
    note.add_argument("--use", default="", help="что соседи обязаны делать с этим (или не делать)")
    note.add_argument("--ref", default="", help="коммит, файл:строка или id ревизии")
    note.set_defaults(func=cmd_note)

    def add_filters(p: argparse.ArgumentParser) -> None:
        p.add_argument("--lane", default="", help="своя дорожка: её записи из конспекта убираются")
        p.add_argument("--all-lanes", action="store_true", help="не убирать записи своей дорожки")
        p.add_argument("--ticket", default="", help="только записи этого тикета")
        p.add_argument("--kind", default="", help="виды через запятую")
        p.add_argument("--like", default="", help="поиск по предмету: имя, кусок detail или use")
        p.add_argument("--name", default="", help="то же, что --like")
        p.add_argument("--since", default="", help="YYYY-MM-DD, по умолчанию вся доска")
        p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)

    brief = sub.add_parser("brief", help="конспект для промпта или поиск по предмету")
    add_filters(brief)
    brief.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    brief.set_defaults(func=cmd_brief)

    allc = sub.add_parser("all", help="вся доска целиком")
    add_filters(allc)
    allc.add_argument("--json", action="store_true")
    allc.add_argument("--raw", action="store_true", help="без свёртки: показать и claim, и dropped")
    allc.set_defaults(func=cmd_all)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if getattr(args, "since", "") == "today":
        args.since = today()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
