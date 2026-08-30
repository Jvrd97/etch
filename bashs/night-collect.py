#!/usr/bin/env python3
# [review:need-review] PHASE-03/night-run
# summary: отбор тикетов для ночного прогона — читает шапки issues/PHASE-*/{backlog,in-work},
#          отсеивает неисполнимые без человека, упорядочивает и печатает список путей.
#
# Печатает в stdout TSV: путь \t id \t estimate \t заголовок.
# В --dropped-out (если задан) пишет TSV: id \t причина \t подробность — это вход для
# сводки ночи, чтобы утром было видно не только что взяли, но и что не взяли и почему.
#
# Почему python, а не bash-фильтры как в alv: alv отбирал тремя грепами и одной
# python-вставкой для round-robin. Здесь round-robin не нужен (сервисов нет), зато нужны
# разбор блокеров по правилам TRIAGE_PROMPT, поиск блокера глобом по всему дереву issues/
# и порядок по оценке. На bash 3.2 это было бы длиннее и хуже читалось.
#
# Форматы шапки читаются оба — YAML-frontmatter и markdown-шапка `**Type**:`. В этом
# репозитории frontmatter нет ни у одного тикета, но читалка двухформатная намеренно:
# в alv однoформатное чтение один раз уже собрало в автономный прогон тикет с пометкой
# «НЕ БРАТЬ». Дешевле держать обе ветки, чем ловить это ещё раз.

import argparse
import glob
import os
import re
import subprocess
import sys

# Папки-статусы. PRDs/ исключён намеренно: там своя нумерация (01-, 02-, 03-),
# которая пересекается с номерами тикетов и один раз уже сломала триаж.
STATUS_DIRS = ("backlog", "in-work", "done", "rejected", "concerns")
CLOSED_DIRS = ("done",)

EST_ORDER = {"S": 0, "M": 1, "L": 2, "XL": 3, "": 4}


def field(text: str, key: str, label: str) -> str:
    """Значение поля шапки. Сначала YAML-frontmatter, потом markdown-строка `**Label**:`."""
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end > 0:
            for line in text[4:end].splitlines():
                if line.strip().startswith(key + ":"):
                    return line.split(":", 1)[1].strip()
    m = re.search(r"^(?:- )?\*\*%s\*\*:\s*(.*)$" % re.escape(label), text, re.M | re.I)
    return m.group(1).strip() if m else ""


def norm_type(raw: str) -> str:
    """«AFK (backend-слайс; consent-UI iOS)» → AFK: скобка это заметка, а не другой тип."""
    return re.sub(r"[\[\](),.]", "", raw.split()[0]) if raw.split() else ""


def norm_est(raw: str) -> str:
    """«S (~3 агент-часа)» → S."""
    m = re.match(r"\s*([A-Za-z]{1,2})\b", raw)
    return m.group(1).upper() if m else ""


def dep_ids(raw: str, own: str) -> list[str]:
    """Номера блокеров. Правила те же, что в TRIAGE_PROMPT петли, только исполняет их код.

    1) вырезать содержимое обратных кавычек — там пути и имена файлов;
    2) отрезать хвост-объяснение по первому —, – , ; или точке с пробелом;
    3) выбросить токены со слэшем (это пути, а не номера);
    4) взять [#NNN] и голые числа 1-4 знаков; свой номер и дубли убрать.
    """
    if not raw or raw.strip().lower() in {"none", "нет", "-", "—", "n/a"}:
        return []
    s = re.sub(r"`[^`]*`", " ", raw)
    s = re.split(r"[—–;]|\.\s", s, maxsplit=1)[0]
    out: list[str] = []
    for tok in re.split(r"[\s,\[\]]+", s):
        if not tok or "/" in tok:
            continue
        m = re.fullmatch(r"#?(\d{1,4})", tok)
        if not m:
            continue
        num = m.group(1).lstrip("0") or "0"
        if num != own and num not in out:
            out.append(num)
    return out


def blocker_status(root: str, num: str) -> str:
    """Статус блокера = имя lifecycle-папки его файла. Не нашли — 'missing'."""
    for d in STATUS_DIRS:
        hits = glob.glob(os.path.join(root, "issues", "PHASE-*", d, f"{num}-*.md"))
        hits += glob.glob(os.path.join(root, "issues", "PHASE-*", d, f"{num}.md"))
        if hits:
            return d
    return "missing"


def has_native_layer(text: str) -> str:
    """Слой Mac/iOS в «Vertical Slice Layers». Петля Swift не собирает и каталога
    habit-tracker/mac не существует — такой тикет она закроет молча наполовину."""
    block = re.search(r"^## Vertical Slice Layers\s*$(.*?)^## ", text, re.M | re.S)
    body = block.group(1) if block else text
    m = re.search(r"^\s*-\s*\[[ x]\]\s*(Mac|iOS)\b", body, re.M | re.I)
    return m.group(1) if m else ""


def committed_numbers(root: str, phase: str) -> set[str]:
    """Номера, уже упомянутые в истории ветки как <PHASE>/<N>.

    Волна B закрыла #90 и #93 коммитом, а файлы тикетов остались в backlog/. Preflight
    вернёт по ним already-done и это правильно, но каждый сожжёт агента впустую.
    """
    try:
        out = subprocess.run(
            ["git", "-C", root, "log", "--format=%s%n%b", "-n", "400"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return set()
    return {m.group(1) for m in re.finditer(rf"{re.escape(phase)}/(\d{{1,4}})(?!\d)", out)}


def result_status(results_dir: str, tid: str) -> str:
    path = os.path.join(results_dir, f"{tid}.json")
    if not os.path.isfile(path):
        return ""
    try:
        import json
        return json.load(open(path)).get("status", "")
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--phase", default="PHASE-03")
    ap.add_argument("--max", type=int, default=6)
    ap.add_argument("--skip", default="", help="номера тикетов через запятую")
    ap.add_argument("--results-dir", default="")
    ap.add_argument("--dropped-out", default="")
    ap.add_argument("--allow-native", action="store_true",
                    help="не отсеивать тикеты со слоем Mac/iOS")
    ap.add_argument("--allow-committed", action="store_true",
                    help="не отсеивать тикеты, чей номер уже есть в истории коммитов")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    base = os.path.join(root, "issues", args.phase)
    skip = {s.strip().lstrip("#") for s in args.skip.split(",") if s.strip()}
    committed = set() if args.allow_committed else committed_numbers(root, args.phase)

    files: list[str] = []
    for d in ("backlog", "in-work"):
        files += sorted(glob.glob(os.path.join(base, d, "*.md")))

    picked: list[dict] = []
    dropped: list[tuple[str, str, str]] = []

    for path in files:
        name = os.path.basename(path)
        m = re.match(r"^(\d+)-", name)
        if not m:
            continue
        tid = m.group(1)
        text = open(path, encoding="utf-8", errors="replace").read()
        title = ""
        h1 = re.search(r"^#\s+(.+)$", text, re.M)
        if h1:
            title = h1.group(1).strip()

        if tid in skip:
            dropped.append((tid, "skip", "снят флагом -x"))
            continue

        ttype = norm_type(field(text, "type", "Type"))
        if ttype and ttype.upper() != "AFK":
            dropped.append((tid, "type", ttype))
            continue

        if not args.allow_native:
            native = has_native_layer(text)
            if native:
                dropped.append((tid, "native-layer", f"слой {native}: петля его не собирает"))
                continue

        if tid in committed:
            dropped.append((tid, "already-committed", f"номер уже в истории ветки как {args.phase}/{tid}"))
            continue

        if args.results_dir:
            st = result_status(args.results_dir, tid)
            if st in ("PASS", "BLOCKED", "NEEDS_HUMAN", "ALREADY_DONE"):
                dropped.append((tid, "final-result", f"вердикт {st} уже лежит в results/"))
                continue

        deps = dep_ids(field(text, "blocked_by", "Blocked by"), tid)
        open_deps = [f"{d}:{blocker_status(root, d)}" for d in deps
                     if blocker_status(root, d) not in CLOSED_DIRS]
        if open_deps:
            dropped.append((tid, "blocked", ", ".join(open_deps)))
            continue

        picked.append({
            "path": path, "id": tid, "est": norm_est(field(text, "estimated", "Estimated")),
            "title": title,
        })

    # Порядка по зависимостям внутри волны не бывает по построению: тикет попадает в волну
    # только когда ВСЕ его блокеры уже в done/, значит связей внутри набора нет. Топологию
    # задаёт последовательность волн, а порядок внутри волны — оценка: короткие первыми,
    # тогда к утру закрытых тикетов больше, а оборванной работы меньше.
    picked.sort(key=lambda t: (EST_ORDER.get(t["est"], 4), int(t["id"])))
    picked = picked[: args.max]

    if args.dropped_out:
        with open(args.dropped_out, "w", encoding="utf-8") as fh:
            for tid, reason, detail in sorted(dropped, key=lambda r: int(r[0])):
                fh.write(f"{tid}\t{reason}\t{detail}\n")

    for t in picked:
        print(f"{t['path']}\t{t['id']}\t{t['est']}\t{t['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
