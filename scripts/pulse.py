#!/usr/bin/env python3
# [review:need-review] pulse-setup
# summary: project pulse — SQLite of features, phases and checks; CLI behind progress/brief/mark (copy of ~/.claude/skills/pulse-setup/assets/pulse.py)
"""Пульс проекта LoopLab: SQLite со всеми функциями, фазы и шкала готовности.

Что здесь хранится. Каждая функция каталога (docs/CHECKLIST.md, 2000+ пунктов) — строка таблицы
`features`; фазы проекта — таблица `phases`; каждая правка — строка журнала `events`. База одна на
все worktree и все сессии (лежит рядом с общим `.git`), поэтому состояние живое: агент отметил
функцию — шкала у всех сдвинулась сразу. Читает базу мод `project-pulse` (шкала над вводом и панель
фаз), правит её тот же скрипт — человек и Claude через один и тот же полный CRUD.

Каталог CHECKLIST.md остаётся в git как проверяемая форма. `sync` сводит базу и файл трёхсторонне:
у каждой функции запомнена строка файла на момент прошлой сводки (`base_sig`), поэтому видно, кто
менял — файл (`checklist.py mark`, ручная правка) или база. Менял один — его правка переносится
в другого; менял оба — конфликт: решает `--prefer md|db`, без флага выводится список.
Запускай `sync` на `main` (там каталог, который видит рой).

Команды (везде `--json` — машинный ответ):
  init [--bare]                создать базу, фазы по приоритетам, загрузить каталог (--bare — без каталога)
  import ФАЙЛ|- [--source S]   пакет функций JSON из другого источника: CRM, документы, код; новые создаются, известные обновляются
  check ID KIND ok|fail [--detail Т]   записать проверку функции (KIND: crm, docs, code, test, hands)
  verified                     сколько функций проверено и какие проверки провалены
  sync [--prefer md|db]        свести базу и docs/CHECKLIST.md
  progress [--by phase|prefix|section] [--json]
                               шкала готовности: итого, по фазам, по разделам
  list [--status x|~|_|-] [--phase ID] [--prefix DEV] [--prio P1] [--q ТЕКСТ] [--limit N]
  next [N] [--phase ID]        ближайшие открытые функции: фаза, приоритет, частично раньше «нет»
  get ID                       одна функция со всей историей
  add ID PRIO ТЕКСТ [--status S] [--section РАЗДЕЛ] [--phase ID]
  update ID [--status S] [--prio P] [--text Т] [--where Т] [--review] [--phase ID|-] [--section Р]
  mark ID S [--review] [--where Т]     то же, что у checklist.py (S: x, ~, _, -)
  delete ID                    убрать функцию (из каталога строка исчезнет при sync)
  phase list | add ИМЯ [--goal Т] [--prio P0..P3] [--ord N] | update ID [--name Н] [--goal Т] [--prio P|-] [--ord N]
        | delete ID | assign ID ФУНКЦИЯ [ФУНКЦИЯ…]
  events [N]                   журнал последних правок
  version                      число, растущее на каждую правку (мод опрашивает его)
  brief                        одна строка состояния для хука SessionStart: готовность, фаза, что открыто

Готовность — как в checklist.py: (сделано + ½ частично) / (всего − «не делаем»).
Статус в командах: x сделано, ~ частично, _ (или пробел) нет, - не делаем.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

# Разбор каталога — копия правил scripts/checklist.py: pulse.py кладут и в проекты без него.
ITEM = re.compile(r"^- \[([ ~x\-])\] ([A-Z][A-Z0-9]{1,5}-\d{3}) (P[0-3]) (.+)$")
REVIEW = re.compile(r" · ревью (\d{4}-\d{2}-\d{2})\s*$")
FEATURE_ID = re.compile(r"[A-Z][A-Z0-9]{1,5}-\d{1,6}[A-Z]?")  # DEV-009, CRM-1234, SW-30D: номера длиннее, у подзадач буква


class Item:
    def __init__(self, line_no: int, status: str, id: str, prio: str, text: str, section: str, reviewed: str | None):
        self.line_no, self.status, self.id, self.prio, self.text, self.section, self.reviewed = line_no, status, id, prio, text, section, reviewed


def checklist_path(root: Path) -> Path:
    return root / "docs" / "CHECKLIST.md"


def parse_catalog(path: Path) -> tuple[list[Item], list[str]]:
    items: list[Item] = []
    errors: list[str] = []
    section = "—"
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw.startswith("## "):
            section = raw[3:].strip()
            continue
        if not raw.startswith("- ["):
            continue
        m = ITEM.match(raw)
        if not m:
            errors.append(f"{i}: строка пункта не по формату: {raw[:90]}")
            continue
        status, iid, prio, text = m.groups()
        r = REVIEW.search(text)
        items.append(Item(i, status, iid, prio, text, section, r.group(1) if r else None))
    return items, errors


def repo_root(start: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

STATUSES = {"x": "сделано", "~": "частично", " ": "нет", "-": "не делаем"}
PRIOS = ("P0", "P1", "P2", "P3")
DEFAULT_PHASES = [  # пока у проекта нет своих фаз (CRM, дорожная карта): по приоритетам
    ("Фаза 0 · Основа", "Без этого продукт не работает (P0)", "P0"),
    ("Фаза 1 · Полноценный продукт", "То, чего ждёшь от готового продукта (P1)", "P1"),
    ("Фаза 2 · Продвинутое", "Продвинутые возможности (P2)", "P2"),
    ("Фаза 3 · Экзотика", "Редкое и необязательное (P3)", "P3"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS phases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  goal TEXT NOT NULL DEFAULT '',
  ord INTEGER NOT NULL DEFAULT 0,
  prio TEXT,                       -- функции этого приоритета без своей фазы попадают сюда
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS phases_prio ON phases(prio) WHERE prio IS NOT NULL;
CREATE TABLE IF NOT EXISTS features (
  id TEXT PRIMARY KEY,             -- DEV-009
  prefix TEXT NOT NULL,
  prio TEXT NOT NULL,
  status TEXT NOT NULL,            -- 'x' '~' ' ' '-'
  text TEXT NOT NULL,              -- описание и «где», как в каталоге, без метки ревью
  section TEXT NOT NULL DEFAULT '',
  phase_id INTEGER REFERENCES phases(id) ON DELETE SET NULL,
  reviewed TEXT,                   -- YYYY-MM-DD
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  base_sig TEXT,                   -- строка каталога на момент прошлого sync; NULL — ещё не в файле
  dirty INTEGER NOT NULL DEFAULT 0,-- правили в базе после sync
  deleted INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'checklist',  -- checklist | crm | docs | code | свой
  ref TEXT NOT NULL DEFAULT ''               -- ссылка на источник: номер тикета CRM, путь к документу, файл кода
);
CREATE INDEX IF NOT EXISTS features_status ON features(status) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS features_phase ON features(phase_id);
CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feature_id TEXT NOT NULL,
  kind TEXT NOT NULL,              -- crm | docs | code | test | hands
  ok INTEGER NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL,
  who TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS checks_feature ON checks(feature_id);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  who TEXT NOT NULL,
  kind TEXT NOT NULL,
  target TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
"""


class PulseError(Exception):
    """Понятная пользователю ошибка: печатается одной строкой, без трассировки."""


# ---------- Где база ----------


def git(root: Path, *args: str) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def project_root(start: Path | None = None) -> Path:
    root = repo_root(start or Path(os.environ.get("CLAUDE_PROJECT_DIR") or "."))
    if not root:
        raise PulseError("это не git-репозиторий")
    return root


def db_path(root: Path) -> Path:
    """Одна база на все worktree: рядом с общим `.git` главной копии."""
    if os.environ.get("PULSE_DB"):
        return Path(os.environ["PULSE_DB"])
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    base = Path(common).parent if common else root
    return base / ".looplab" / "pulse.db"


def now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def connect(path: Path, create: bool = False) -> sqlite3.Connection:
    if not path.exists() and not create:
        raise PulseError(f"базы нет: {path} — выполни `python3 scripts/pulse.py init`")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    cols = {r["name"] for r in db.execute("PRAGMA table_info(features)")}
    for col, ddl in (("source", "TEXT NOT NULL DEFAULT 'checklist'"), ("ref", "TEXT NOT NULL DEFAULT ''")):
        if col not in cols:
            db.execute(f"ALTER TABLE features ADD COLUMN {col} {ddl}")
    return db


def who() -> str:
    return os.environ.get("PULSE_WHO") or os.environ.get("USER") or "cli"


def log(db: sqlite3.Connection, kind: str, target: str, detail: str = "") -> None:
    db.execute("INSERT INTO events(at, who, kind, target, detail) VALUES (?,?,?,?,?)", (now(), who(), kind, target, detail))
    db.execute("INSERT INTO meta(key, value) VALUES ('version','1') ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")


# ---------- Строка каталога ----------

REVIEW_STATUSES = "x~"
CHECK_KINDS = ("crm", "docs", "code", "test", "hands")


def line_of(f: sqlite3.Row | dict) -> str:
    review = f" · ревью {f['reviewed']}" if f["reviewed"] and f["status"] in REVIEW_STATUSES else ""
    return f"- [{f['status']}] {f['id']} {f['prio']} {f['text']}{review}"


def sig(line: str) -> str:
    return hashlib.sha1(line.encode("utf-8")).hexdigest()[:16]


def split_text(text: str) -> tuple[str, str | None]:
    m = REVIEW.search(text)
    return (REVIEW.sub("", text).rstrip(), m.group(1) if m else None)


def norm_status(s: str) -> str:
    s = " " if s in ("_", "") else s
    if s not in STATUSES:
        raise PulseError("статус: x, ~, _ (нет), -")
    return s


def norm_prio(p: str) -> str:
    p = p.upper()
    if p not in PRIOS:
        raise PulseError("приоритет: P0, P1, P2, P3")
    return p


def prefix_of(fid: str) -> str:
    return fid.split("-")[0]


# ---------- Фазы ----------


def phase_row(db: sqlite3.Connection, pid: int) -> sqlite3.Row:
    r = db.execute("SELECT * FROM phases WHERE id = ?", (pid,)).fetchone()
    if not r:
        raise PulseError(f"фазы {pid} нет")
    return r


def ensure_default_phases(db: sqlite3.Connection) -> None:
    if db.execute("SELECT 1 FROM phases LIMIT 1").fetchone():
        return
    for i, (name, goal, prio) in enumerate(DEFAULT_PHASES):
        db.execute("INSERT INTO phases(name, goal, ord, prio, created_at, updated_at) VALUES (?,?,?,?,?,?)", (name, goal, i, prio, now(), now()))


EFFECTIVE_PHASE = "COALESCE(f.phase_id, (SELECT id FROM phases p WHERE p.prio = f.prio))"


# ---------- Чтение ----------


def feature_dict(r: sqlite3.Row) -> dict:
    d = {k: r[k] for k in ("id", "prio", "status", "text", "section", "reviewed", "phase_id", "updated_at", "source", "ref")}
    d["status_name"] = STATUSES[r["status"]]
    d["title"] = r["text"].split(" — ")[0]
    if "phase" in r.keys():
        d["phase"] = r["phase"]
    return d


def get_feature(db: sqlite3.Connection, fid: str) -> sqlite3.Row:
    r = db.execute("SELECT * FROM features WHERE id = ? AND deleted = 0", (fid,)).fetchone()
    if not r:
        raise PulseError(f"{fid} не найден")
    return r


def counts(rows) -> dict:
    c = {"total": 0, "done": 0, "partial": 0, "none": 0, "wontdo": 0, "reviewed": 0}
    key = {"x": "done", "~": "partial", " ": "none", "-": "wontdo"}
    for status, reviewed, n in rows:
        c["total"] += n
        c[key[status]] += n
        if reviewed:
            c["reviewed"] += n
    scope = c["total"] - c["wontdo"]
    c["percent"] = round(100 * (c["done"] + 0.5 * c["partial"]) / scope, 1) if scope else 0.0
    c["open"] = c["none"] + c["partial"]
    return c


def progress(db: sqlite3.Connection, by: str = "phase") -> dict:
    base = "FROM features f WHERE f.deleted = 0"
    total = counts(db.execute(f"SELECT status, reviewed IS NOT NULL, COUNT(*) {base} GROUP BY status, reviewed IS NOT NULL").fetchall())
    phases = []
    for p in db.execute("SELECT * FROM phases ORDER BY ord, id").fetchall():
        rows = db.execute(f"SELECT f.status, f.reviewed IS NOT NULL, COUNT(*) {base} AND {EFFECTIVE_PHASE} = ? GROUP BY 1, 2", (p["id"],)).fetchall()
        phases.append({"id": p["id"], "name": p["name"], "goal": p["goal"], "prio": p["prio"], **counts(rows)})
    orphan = db.execute(f"SELECT f.status, f.reviewed IS NOT NULL, COUNT(*) {base} AND {EFFECTIVE_PHASE} IS NULL GROUP BY 1, 2").fetchall()
    out = {"at": now(), "version": version(db), "total": total, "phases": phases}
    if orphan:
        out["no_phase"] = counts(orphan)
    if by in ("prefix", "section"):
        col = "f.prefix" if by == "prefix" else "f.section"
        groups = []
        for (name,) in db.execute(f"SELECT DISTINCT {col} {base} ORDER BY 1").fetchall():
            rows = db.execute(f"SELECT f.status, f.reviewed IS NOT NULL, COUNT(*) {base} AND {col} = ? GROUP BY 1, 2", (name,)).fetchall()
            groups.append({"name": name, **counts(rows)})
        out[f"by_{by}"] = sorted(groups, key=lambda g: (-g["open"], g["name"]))
    return out


def version(db: sqlite3.Connection) -> int:
    r = db.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
    return int(r["value"]) if r else 0


def query(db: sqlite3.Connection, status=None, phase=None, prefix=None, prio=None, q=None, limit=50, order_open=False) -> list[dict]:
    where, args = ["f.deleted = 0"], []
    if status:
        where.append("f.status = ?")
        args.append(norm_status(status))
    if phase is not None:
        where.append(f"{EFFECTIVE_PHASE} = ?")
        args.append(phase)
    if prefix:
        where.append("f.prefix = ?")
        args.append(prefix.upper())
    if prio:
        where.append("f.prio = ?")
        args.append(norm_prio(prio))
    if q:
        where.append("(f.text LIKE ? OR f.id LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    if order_open:
        where.append("f.status IN (' ', '~')")
    order = "f.prio, f.status != '~', f.id" if order_open else "f.id"
    sql = f"SELECT f.*, (SELECT name FROM phases p WHERE p.id = {EFFECTIVE_PHASE}) AS phase FROM features f WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?"
    return [feature_dict(r) for r in db.execute(sql, (*args, limit)).fetchall()]


# ---------- CRUD функций ----------


def add_feature(db, fid, prio, text, status=" ", section="", phase=None, reviewed=None, source="checklist", ref="") -> None:
    if not FEATURE_ID.fullmatch(fid):
        raise PulseError("ID вида PREFIX-123 (префикс из 2–6 заглавных букв или цифр, номер до 6 цифр, после номера может быть буква: SW-30D)")
    if db.execute("SELECT 1 FROM features WHERE id = ?", (fid,)).fetchone():
        raise PulseError(f"{fid} уже есть")
    if phase is not None:
        phase_row(db, phase)
    text, rev = split_text(text)
    reviewed = reviewed or rev
    db.execute(
        "INSERT INTO features(id, prefix, prio, status, text, section, phase_id, reviewed, created_at, updated_at, dirty, source, ref) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)",
        (fid, prefix_of(fid), norm_prio(prio), norm_status(status), text, section, phase, reviewed, now(), now(), source, ref),
    )
    log(db, "add", fid, f"{norm_prio(prio)} {text[:80]}")


def update_feature(db, fid, status=None, prio=None, text=None, where=None, review=False, phase=None, clear_phase=False, section=None) -> sqlite3.Row:
    f = get_feature(db, fid)
    new = {"status": f["status"], "prio": f["prio"], "text": f["text"], "reviewed": f["reviewed"], "phase_id": f["phase_id"], "section": f["section"]}
    changes = []
    if status is not None:
        new["status"] = norm_status(status)
    if prio is not None:
        new["prio"] = norm_prio(prio)
    if text is not None:
        new["text"], rev = split_text(text)
        new["reviewed"] = rev or new["reviewed"]
    if where and where.strip() and where.strip() not in new["text"]:
        new["text"] += f" — {where.strip()}"
    if section is not None:
        new["section"] = section
    if clear_phase:
        new["phase_id"] = None
    elif phase is not None:
        phase_row(db, phase)
        new["phase_id"] = phase
    if review:
        new["reviewed"] = dt.date.today().isoformat()
    if new["status"] not in REVIEW_STATUSES:
        new["reviewed"] = None  # ревью бывает только у «сделано» и «частично», как проверяет checklist.py check
    for k in new:
        if new[k] != f[k]:
            changes.append(f"{k}: {f[k]} → {new[k]}")
    if not changes:
        return f
    db.execute(
        "UPDATE features SET status=?, prio=?, text=?, reviewed=?, phase_id=?, section=?, updated_at=?, dirty=1 WHERE id=?",
        (new["status"], new["prio"], new["text"], new["reviewed"], new["phase_id"], new["section"], now(), fid),
    )
    log(db, "update", fid, "; ".join(c[:90] for c in changes))
    return get_feature(db, fid)


def import_features(db, rows: list[dict], who_source: str = "import") -> dict:
    """Пакет функций из другого источника (CRM, документы, код): новые создаются, известные — обновляются.

    Поля строки: id, text; необязательно prio (по умолчанию P1), status, section, phase, source, ref.
    Статус известной функции пакет не понижает: «сделано» остаётся, пока его не сняли явно (`replace_status`).
    """
    rep = {"added": 0, "updated": 0, "skipped": []}
    for row in rows:
        fid = str(row.get("id", "")).strip()
        try:
            if not FEATURE_ID.fullmatch(fid):
                raise PulseError("ID вида PREFIX-123 или PREFIX-12A")
            text = str(row.get("text") or "").strip()
            if not text:
                raise PulseError("нет text")
            source = str(row.get("source") or who_source)
            ref = str(row.get("ref") or "")
            prio = str(row.get("prio") or "P1")
            exists = db.execute("SELECT 1 FROM features WHERE id = ? AND deleted = 0", (fid,)).fetchone()
            if not exists:
                add_feature(db, fid, prio, text, str(row.get("status") or " "), str(row.get("section") or ""), row.get("phase"), None, source, ref)
                rep["added"] += 1
                continue
            f = get_feature(db, fid)
            keep = row.get("replace_status") is not True and f["status"] in "x~" and (row.get("status") in (None, " ", "_"))
            update_feature(db, fid, status=None if keep or row.get("status") is None else str(row["status"]), prio=prio if row.get("prio") else None, text=text, section=row.get("section"), phase=row.get("phase"))
            db.execute("UPDATE features SET source = ?, ref = ? WHERE id = ?", (source, ref or f["ref"], fid))
            rep["updated"] += 1
        except PulseError as e:
            rep["skipped"].append({"id": fid or "?", "why": str(e)})
    if rep["added"] or rep["updated"]:
        log(db, "import", who_source, f"добавлено {rep['added']}, обновлено {rep['updated']}")
    return rep


def record_check(db, fid: str, kind: str, ok: bool, detail: str = "") -> None:
    """Запись проверки функции: чем проверено (crm, docs, code, test, hands) и чем кончилось."""
    if kind not in CHECK_KINDS:
        raise PulseError(f"вид проверки: {', '.join(CHECK_KINDS)}")
    get_feature(db, fid)
    db.execute("INSERT INTO checks(feature_id, kind, ok, detail, at, who) VALUES (?,?,?,?,?,?)", (fid, kind, int(ok), detail, now(), who()))
    log(db, "check", fid, f"{kind} {'ok' if ok else 'FAIL'} {detail[:80]}")


def checks_of(db, fid: str) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT kind, ok, detail, at, who FROM checks WHERE feature_id = ? ORDER BY id DESC", (fid,))]


def verified(db) -> dict:
    """Сколько функций проверено, по виду проверки: последняя проверка каждого вида должна быть успешной."""
    out: dict = {"with_checks": 0, "all_ok": 0, "failing": []}
    for (fid,) in db.execute("SELECT DISTINCT feature_id FROM checks").fetchall():
        last: dict[str, int] = {}
        for k, ok in db.execute("SELECT kind, ok FROM checks WHERE feature_id = ? ORDER BY id", (fid,)):
            last[k] = ok
        out["with_checks"] += 1
        if all(last.values()):
            out["all_ok"] += 1
        else:
            out["failing"].append(fid)
    return out


def delete_feature(db, fid) -> None:
    get_feature(db, fid)
    db.execute("UPDATE features SET deleted = 1, dirty = 1, updated_at = ? WHERE id = ?", (now(), fid))
    log(db, "delete", fid)


# ---------- sync с docs/CHECKLIST.md ----------


def sync(db: sqlite3.Connection, root: Path, prefer: str | None = None) -> dict:
    path = checklist_path(root)
    if not path.exists():
        raise PulseError(f"нет {path}")
    items, errors = parse_catalog(path)
    if errors:
        raise PulseError("каталог не по формату, сначала `python3 scripts/checklist.py check`: " + errors[0])
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    by_id = {it.id: it for it in items}
    rep = {"from_md": 0, "to_md": 0, "added_to_db": 0, "added_to_md": 0, "removed_from_db": 0, "removed_from_md": 0, "conflicts": []}
    ensure_default_phases(db)
    rows = {r["id"]: r for r in db.execute("SELECT * FROM features WHERE source = 'checklist'").fetchall()}
    edits: dict[int, str | None] = {}  # номер строки (0-based) → новая строка; None — убрать

    def md_row(it: Item) -> dict:
        text, rev = split_text(it.text)
        return {"status": it.status, "prio": it.prio, "text": text, "reviewed": rev}

    def take_md(fid: str, it: Item, new: bool) -> None:
        d = md_row(it)
        line = lines[it.line_no - 1].rstrip("\n")
        if new:
            db.execute(
                "INSERT INTO features(id, prefix, prio, status, text, section, reviewed, created_at, updated_at, base_sig, dirty) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                (fid, prefix_of(fid), d["prio"], d["status"], d["text"], it.section, d["reviewed"], now(), now(), sig(line)),
            )
        else:
            db.execute(
                "UPDATE features SET prio=?, status=?, text=?, reviewed=?, section=?, base_sig=?, dirty=0, updated_at=? WHERE id=?",
                (d["prio"], d["status"], d["text"], d["reviewed"], it.section, sig(line), now(), fid),
            )

    for fid, it in by_id.items():
        line = lines[it.line_no - 1].rstrip("\n")
        r = rows.get(fid)
        if r is None:
            take_md(fid, it, new=True)
            rep["added_to_db"] += 1
            continue
        if r["deleted"]:
            if sig(line) == r["base_sig"] or prefer == "db":
                edits[it.line_no - 1] = None
                rep["removed_from_md"] += 1
            elif prefer == "md":
                take_md(fid, it, new=False)
                db.execute("UPDATE features SET deleted = 0 WHERE id = ?", (fid,))
                rep["from_md"] += 1
            else:
                rep["conflicts"].append({"id": fid, "what": "удалена в базе, но строка в каталоге изменилась"})
            continue
        md_changed = sig(line) != r["base_sig"]
        db_changed = bool(r["dirty"])
        if md_changed and db_changed and sig(line) != sig(line_of(r)):
            if prefer == "md":
                take_md(fid, it, new=False)
                rep["from_md"] += 1
            elif prefer == "db":
                edits[it.line_no - 1] = line_of(r) + "\n"
                db.execute("UPDATE features SET base_sig=?, dirty=0 WHERE id=?", (sig(line_of(r)), fid))
                rep["to_md"] += 1
            else:
                rep["conflicts"].append({"id": fid, "what": "изменена и в каталоге, и в базе", "md": line[:120], "db": line_of(r)[:120]})
        elif md_changed:
            take_md(fid, it, new=False)
            rep["from_md"] += 1
        elif db_changed:
            edits[it.line_no - 1] = line_of(r) + "\n"
            db.execute("UPDATE features SET base_sig=?, dirty=0 WHERE id=?", (sig(line_of(r)), fid))
            rep["to_md"] += 1
    # в базе есть, в каталоге нет
    adds: list[sqlite3.Row] = []
    for fid, r in rows.items():
        if fid in by_id:
            continue
        if r["deleted"]:
            db.execute("DELETE FROM features WHERE id = ?", (fid,))
        elif r["base_sig"] is None:
            adds.append(r)  # создана в базе
        elif r["dirty"] and prefer != "md":
            adds.append(r)  # из каталога убрали, а в базе её правили после сводки: возвращаем в каталог
        else:
            db.execute("DELETE FROM features WHERE id = ?", (fid,))
            rep["removed_from_db"] += 1
    new_lines = apply_edits(lines, edits, items, adds)
    rep["added_to_md"] = len(adds)
    if new_lines != lines:
        path.write_text("".join(new_lines), encoding="utf-8")
    for r in adds:
        db.execute("UPDATE features SET base_sig = ?, dirty = 0 WHERE id = ?", (sig(line_of(r)), r["id"]))
    for fid in [r["id"] for r in db.execute("SELECT id FROM features WHERE deleted = 1 AND source = 'checklist'").fetchall()]:
        db.execute("DELETE FROM features WHERE id = ?", (fid,))
    if rep["from_md"] or rep["to_md"] or rep["added_to_db"] or rep["added_to_md"] or rep["removed_from_db"] or rep["removed_from_md"]:
        log(db, "sync", "CHECKLIST.md", json.dumps({k: v for k, v in rep.items() if k != "conflicts" and v}, ensure_ascii=False))
    return rep


def apply_edits(lines: list[str], edits: dict[int, str | None], items: list[Item], adds: list[sqlite3.Row]) -> list[str]:
    """Замены и удаления строк по номеру, новые функции — в конец своего раздела."""
    out = list(lines)
    # где кончается каждый раздел: номер последней строки пункта в нём
    last_in_section: dict[str, int] = {}
    last_by_prefix: dict[str, int] = {}
    for it in items:
        last_in_section[it.section] = it.line_no - 1
        last_by_prefix[prefix_of(it.id)] = it.line_no - 1
    journal = next((i for i, ln in enumerate(lines) if ln.startswith("## Журнал")), len(lines))
    inserts: dict[int, list[str]] = {}
    for r in adds:
        at = last_in_section.get(r["section"]) if r["section"] else None
        if at is None:
            at = last_by_prefix.get(r["prefix"])
        if at is None:
            at = journal - 1
            while at > 0 and not lines[at].strip():
                at -= 1
        inserts.setdefault(at, []).append(line_of(r) + "\n")
    res: list[str] = []
    for i, ln in enumerate(out):
        if i in edits:
            if edits[i] is not None:
                res.append(edits[i])  # type: ignore[arg-type]  # mypy does not narrow a dict item after the None check above
        else:
            res.append(ln)
        res.extend(inserts.get(i, []))
    return res


# ---------- Печать ----------


def bar(p: float, width: int = 24) -> str:
    n = round(width * p / 100)
    return "█" * n + "░" * (width - n)


def current_phase_id(db: sqlite3.Connection) -> int | None:
    """Текущая фаза — первая по порядку, где ещё есть открытое; всё закрыто — None (тогда без фильтра)."""
    cur = next((ph for ph in progress(db)["phases"] if ph["open"] > 0), None)
    return cur["id"] if cur else None


def brief(db: sqlite3.Connection) -> str:
    p = progress(db)
    t = p["total"]
    cur = next((ph for ph in p["phases"] if ph["open"] > 0), None)
    nxt = query(db, phase=cur["id"] if cur else None, limit=4, order_open=True)  # ближайшие — из текущей фазы
    v = verified(db)
    phase = f" Сейчас: {cur['name']} ({cur['percent']}%, открыто {cur['open']})." if cur else ""
    nxt_text = " Ближайшие: " + "; ".join(f"{r['id']} {r['title'][:50]}" for r in nxt) + "." if nxt else ""
    chk = f" Проверок с провалом: {len(v['failing'])}." if v["failing"] else ""
    return (
        f"Пульс проекта (SQLite, scripts/pulse.py): готовность {t['percent']}% — сделано {t['done']} из {t['total'] - t['wontdo']}, "
        f"частично {t['partial']}, нет {t['none']}.{phase}{chk}{nxt_text} "
        "Состояние живое и общее для всех сессий: `python3 scripts/pulse.py progress`, отметка — `mark ID x --review` после проверки."
    )


def show_progress(p: dict) -> None:
    t = p["total"]
    print(f"Готовность проекта: {t['percent']}%  {bar(t['percent'])}")
    print(f"всего {t['total']} · сделано {t['done']} (ревью {t['reviewed']}) · частично {t['partial']} · нет {t['none']} · не делаем {t['wontdo']}")
    print()
    for ph in p["phases"]:
        print(f"{ph['name']:<30} {ph['percent']:>5}%  {bar(ph['percent'], 20)}  {ph['done']}/{ph['total'] - ph['wontdo']}  открыто {ph['open']}")
    if "no_phase" in p:
        print(f"{'Без фазы':<30} {p['no_phase']['percent']:>5}%  открыто {p['no_phase']['open']}")
    for key in ("by_prefix", "by_section"):
        if key in p:
            print()
            for g in p[key][:30]:
                print(f"{g['name'][:34]:<34} {g['percent']:>5}%  {bar(g['percent'], 16)}  открыто {g['open']}")


def emit(args, data, human=None) -> None:
    if args.json or human is None:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        human(data)


def print_features(rows: list[dict]) -> None:
    for r in rows:
        mark = r["status"] if r["status"] != " " else " "
        print(f"[{mark}] {r['id']} {r['prio']} {r['title'][:90]}  ({r.get('phase') or '—'})")
    print(f"— {len(rows)}")


# ---------- Разбор команд ----------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pulse.py", description="Пульс проекта: SQLite функций, фазы, шкала готовности")
    ap.add_argument("--json", action="store_true", help="ответ JSON")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("init")
    p.add_argument("--bare", action="store_true", help="пустая база без каталога: проект без CHECKLIST.md (функции приходят из CRM, документов, кода)")
    p = sub.add_parser("import")
    p.add_argument("file", help="JSON-массив функций или - (stdin)")
    p.add_argument("--source", default="import")
    p = sub.add_parser("check")
    p.add_argument("id")
    p.add_argument("kind", choices=CHECK_KINDS)
    p.add_argument("result", choices=["ok", "fail"])
    p.add_argument("--detail", default="")
    sub.add_parser("verified")
    p = sub.add_parser("sync")
    p.add_argument("--prefer", choices=["md", "db"])
    p = sub.add_parser("progress")
    p.add_argument("--by", choices=["phase", "prefix", "section"], default="phase")
    p = sub.add_parser("list")
    p.add_argument("--status")
    p.add_argument("--phase", type=int)
    p.add_argument("--prefix")
    p.add_argument("--prio")
    p.add_argument("--q")
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("next")
    p.add_argument("n", nargs="?", type=int, default=15)
    p.add_argument("--phase", type=int)
    sub.add_parser("get").add_argument("id")
    p = sub.add_parser("add")
    p.add_argument("id")
    p.add_argument("prio")
    p.add_argument("text")
    p.add_argument("--status", default=" ")
    p.add_argument("--section", default="")
    p.add_argument("--phase", type=int)
    p = sub.add_parser("update")
    p.add_argument("id")
    p.add_argument("--status")
    p.add_argument("--prio")
    p.add_argument("--text")
    p.add_argument("--where")
    p.add_argument("--review", action="store_true")
    p.add_argument("--phase")
    p.add_argument("--section")
    p = sub.add_parser("mark")
    p.add_argument("id")
    p.add_argument("status")
    p.add_argument("--review", action="store_true")
    p.add_argument("--where")
    sub.add_parser("delete").add_argument("id")
    ph = sub.add_parser("phase")
    ps = ph.add_subparsers(dest="pcmd", required=True)
    ps.add_parser("list")
    p = ps.add_parser("add")
    p.add_argument("name")
    p.add_argument("--goal", default="")
    p.add_argument("--prio")
    p.add_argument("--ord", type=int)
    p = ps.add_parser("update")
    p.add_argument("id", type=int)
    p.add_argument("--name")
    p.add_argument("--goal")
    p.add_argument("--prio")
    p.add_argument("--ord", type=int)
    ps.add_parser("delete").add_argument("id", type=int)
    p = ps.add_parser("assign")
    p.add_argument("id", type=int)
    p.add_argument("features", nargs="+")
    p = sub.add_parser("events")
    p.add_argument("n", nargs="?", type=int, default=20)
    sub.add_parser("version")
    sub.add_parser("brief")
    return ap


def run(args, root: Path) -> int:
    path = db_path(root)
    if args.cmd == "init":
        db = connect(path, create=True)
        ensure_default_phases(db)
        rep = {"added_to_db": 0} if args.bare else sync(db, root)
        db.commit()
        emit(args, {"db": str(path), **rep}, lambda d: print(f"база {d['db']}: загружено функций {d['added_to_db']}"))
        return 0
    db = connect(path)
    if args.cmd == "sync":
        rep = sync(db, root, args.prefer)
        db.commit()
        emit(args, rep, lambda d: print("сводка: из каталога %d, в каталог %d, новых в базе %d, новых в каталоге %d, конфликтов %d" % (d["from_md"], d["to_md"], d["added_to_db"], d["added_to_md"], len(d["conflicts"]))) or [print("  конфликт", c["id"], "—", c["what"]) for c in d["conflicts"]])
        return 1 if rep["conflicts"] else 0
    if args.cmd == "progress":
        emit(args, progress(db, args.by), show_progress)
    elif args.cmd == "list":
        emit(args, query(db, args.status, args.phase, args.prefix, args.prio, args.q, args.limit), print_features)
    elif args.cmd == "next":
        emit(args, query(db, phase=args.phase if args.phase is not None else current_phase_id(db), limit=args.n, order_open=True), print_features)
    elif args.cmd == "get":
        f = get_feature(db, args.id)
        ev = [dict(e) for e in db.execute("SELECT at, who, kind, detail FROM events WHERE target = ? ORDER BY id DESC LIMIT 20", (args.id,))]
        d = {**feature_dict(f), "events": ev, "checks": checks_of(db, args.id), "line": line_of(f)}
        emit(args, d, lambda x: print(x["line"]) or [print("  проверка", c["kind"], "ok" if c["ok"] else "FAIL", c["detail"]) for c in x["checks"]] or [print(" ", e["at"], e["who"], e["kind"], e["detail"]) for e in x["events"]])
    elif args.cmd == "import":
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        try:
            rows = json.loads(text)
        except json.JSONDecodeError as e:
            raise PulseError(f"не JSON: {e}")
        if not isinstance(rows, list):
            raise PulseError("нужен JSON-массив функций")
        emit(args, import_features(db, rows, args.source), lambda d: print(f"добавлено {d['added']}, обновлено {d['updated']}, пропущено {len(d['skipped'])}") or [print("  пропуск", s["id"], "—", s["why"]) for s in d["skipped"]])
    elif args.cmd == "check":
        record_check(db, args.id, args.kind, args.result == "ok", args.detail)
        emit(args, {"id": args.id, "checks": checks_of(db, args.id)}, lambda d: print(f"{args.id}: {args.kind} {args.result}"))
    elif args.cmd == "verified":
        emit(args, verified(db), lambda d: print(f"с проверками {d['with_checks']}, все успешны {d['all_ok']}, есть провал {len(d['failing'])}"))
    elif args.cmd == "add":
        add_feature(db, args.id, args.prio, args.text, args.status, args.section, args.phase)
        emit(args, feature_dict(get_feature(db, args.id)), lambda d: print("добавлено", d["id"]))
    elif args.cmd == "update":
        clear = args.phase == "-"
        f = update_feature(db, args.id, args.status, args.prio, args.text, args.where, args.review, None if clear or args.phase is None else int(args.phase), clear, args.section)
        emit(args, feature_dict(f), lambda d: print(line_of(f)))
    elif args.cmd == "mark":
        f = update_feature(db, args.id, args.status, None, None, args.where, args.review)
        emit(args, feature_dict(f), lambda d: print(line_of(f)))
    elif args.cmd == "delete":
        delete_feature(db, args.id)
        emit(args, {"deleted": args.id}, lambda d: print("убрано", args.id))
    elif args.cmd == "phase":
        phase_cmd(db, args)
    elif args.cmd == "events":
        rows = [dict(e) for e in db.execute("SELECT at, who, kind, target, detail FROM events ORDER BY id DESC LIMIT ?", (args.n,))]
        emit(args, rows, lambda rs: [print(e["at"], e["who"], e["kind"], e["target"], e["detail"][:100]) for e in rs])
    elif args.cmd == "version":
        print(version(db))
    elif args.cmd == "brief":
        print(brief(db))
    else:
        print(__doc__)
        return 2
    db.commit()
    return 0


def phase_cmd(db, args) -> None:
    c = args.pcmd
    if c == "list":
        rows = [dict(r) for r in db.execute("SELECT id, name, goal, ord, prio FROM phases ORDER BY ord, id")]
        emit(args, rows, lambda rs: [print(f"{r['id']}  {r['name']}  [{r['prio'] or 'вручную'}]  {r['goal']}") for r in rs])
    elif c == "add":
        prio = norm_prio(args.prio) if args.prio else None
        order = args.ord if args.ord is not None else (db.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM phases").fetchone()[0])
        try:
            cur = db.execute("INSERT INTO phases(name, goal, ord, prio, created_at, updated_at) VALUES (?,?,?,?,?,?)", (args.name, args.goal, order, prio, now(), now()))
        except sqlite3.IntegrityError:
            raise PulseError(f"приоритет {prio} уже ведёт в другую фазу: сначала phase update ID --prio -")
        log(db, "phase-add", str(cur.lastrowid), args.name)
        emit(args, {"id": cur.lastrowid}, lambda d: print("фаза", d["id"]))
    elif c == "update":
        p = phase_row(db, args.id)
        name = args.name if args.name is not None else p["name"]
        goal = args.goal if args.goal is not None else p["goal"]
        order = args.ord if args.ord is not None else p["ord"]
        prio = None if args.prio == "-" else norm_prio(args.prio) if args.prio else p["prio"]
        try:
            db.execute("UPDATE phases SET name=?, goal=?, ord=?, prio=?, updated_at=? WHERE id=?", (name, goal, order, prio, now(), args.id))
        except sqlite3.IntegrityError:
            raise PulseError(f"приоритет {prio} уже ведёт в другую фазу")
        log(db, "phase-update", str(args.id), name)
        emit(args, {"id": args.id}, lambda d: print("обновлена фаза", args.id))
    elif c == "delete":
        p = phase_row(db, args.id)
        n = db.execute("UPDATE features SET phase_id = NULL, dirty = dirty WHERE phase_id = ?", (args.id,)).rowcount
        db.execute("DELETE FROM phases WHERE id = ?", (args.id,))
        log(db, "phase-delete", str(args.id), f"{p['name']}; функций без своей фазы: {n}")
        emit(args, {"deleted": args.id, "released": n}, lambda d: print(f"фаза убрана, функций освобождено: {n}"))
    elif c == "assign":
        phase_row(db, args.id)
        for fid in args.features:
            update_feature(db, fid, phase=args.id)
        emit(args, {"phase": args.id, "features": args.features}, lambda d: print(f"в фазу {args.id}: {len(args.features)}"))


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--json" in argv:  # --json удобно писать и в конце команды
        argv = ["--json"] + [a for a in argv if a != "--json"]
    args = ap.parse_args(argv)
    if not args.cmd:
        print(__doc__)
        return 0
    try:
        return run(args, project_root())
    except PulseError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
