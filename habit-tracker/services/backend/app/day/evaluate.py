# [review:need-review] PHASE-03/90, PHASE-03/91, PHASE-03/137, PHASE-03/142, PHASE-03/179
# summary: PHASE-03/137 adds the role clause — a workday closes at least one act of a role other than tech lead — and turns the verdict into a derivation over an explicit list of clauses, so a verdict that disagrees with its own clauses has no path to exist
# summary: the verdict of a day as one pure function — `evaluate_day(rule, facts)` with the reasons ordered not_closed → overtime → anchors → tasks, `skipped` out of both denominators and `work_minutes IS NULL` read as "не измерено" rather than as zero; since #142 the order of the reasons and the composition of the anchors come from the rule row (`verdict_rule`, `anchors`) instead of from constants; #179 lets the ceiling of the day come from the profile in force on its date, while the reason stays the same `overtime`
"""
Whether a day was won, decided without a database.

Until now this answer was prose. `## День выигран?` was written by hand, read
back by a regular expression in two independent places (`life.py` and
`plan_server.py`), and the criterion itself existed in three incompatible
versions — `config.md` said all four tasks and eight hours, the `/day-close`
skill said anchors and eighty percent, `templates/summary.md` said ten hours.
Here it is one function over values, and the numbers it compares against come
from the `day_rule_set` row the day was actually lived under.

**The reasons are ordered by which one is worth being sent to repair.**
`not_closed → overtime → anchors → tasks`. Overtime is named before the anchors
not because work outranks health but because it *causes* them: anchors missed
after the ninth hour are a consequence, and pointing at them would send the
reader to fix the wrong thing. Anchors then come before tasks because a day that
failed on both is decided by the anchors. The priority of `config.md` (здоровье
> работа > отношения) is expressed elsewhere: all kinds of anchor weigh the
same, so the evening with the family drops the day exactly where the missed
street does.

**«Все якоря» — это все якоря, вписанные в план этого дня.** The denominator is
counted from lines with `kind='anchor'`, never from `rule.required_anchors`:
that tuple names the five edges a plan *may* mark as `rigidity='hard'`
(`app.day.rules`, `check_hard_rigidity`), and it bounds what a plan may harden
rather than listing what a day must contain. So a day whose plan carries no
anchor line counts 0/0 and passes, exactly as 0/0 tasks passes. It is a hole and
it is a deliberate one for now: an anchor exists only as a line of markdown
until `anchor_kind` / `day_anchor` arrive with `#92`, and a denominator of five
today would call every imported day of August lost for anchors nobody had
anywhere to write down. `tests/test_evaluate_day.py` pins both readings, so
changing this is a decision rather than a side effect.

**Сама формула — строка таблицы, а не эта функция.** `verdict_rule.reason_order`
holds the order, `anchors` holds the composition of the anchors, and both are
read here rather than written here (`#142`). Dropping `anchors` from the order,
or adding a sixth anchor, is a new rule row: yesterday keeps the formula it was
lived under, exactly as it keeps the ceiling of hours. `not_closed` is not in
the list and cannot be — «никто не закрыл день» is the absence of a judgement,
not a condition of one.

**Вердикт выводится из списка клаузов, а не считается рядом с ними.** Каждое
условие канона превращается в `Clause` — код, пройден или нет, и человеческая
расшифровка, — и только потом вердикт становится «есть ли непройденный». Пути,
на котором клаузы говорят одно, а вердикт другое, нет по построению: до `#137`
функция возвращалась на первом же непройденном условии, и «что ещё было не так»
приходилось досчитывать глазами по счётчикам.

**Клауз роли — про акт, а не про долю времени.** Рабочий день, не закрывший ни
одного акта роли из `role_clause_roles`, не выигран. Доли минут в дневной
вердикт не входят намеренно: день из восьми часов ревью стопроцентно тимлидский
по минутам и может нести единственный архитектурный акт, ради которого он и был.
Дневной порог доли объявил бы такой день проигранным по формальному признаку и
создал бы стимул подгонять разметку; доли идут в недельную сводку (`#138`).

Клауз не применяется в нерабочий и в no-code день: `kind` и `is_nocode`
материализованы при создании дня (`#86`), поэтому прошлый вторник остаётся тем,
чем был, даже если расписание недели с тех пор переписали.

**«Не закрыл» и «проиграл» — разные факты.** An unclosed day has no verdict at
all rather than a lost one: nobody has said what happened to it yet, and a
`lost` written by a clock rather than by a person is the one reading that makes
the whole record untrustworthy.

**`work_minutes IS NULL` means "не измерено", never zero.** Since `#91` the
number is measured by the `work_interval` rows of the day; a day with none of
them carries no number at all. Such a day skips the overtime check and says so
in `missing_data`, because calling it clean would be exactly as wrong as calling
it overtime.

Nothing here touches the session, FastAPI or `app.crud`, by the same reasoning
as `app.health.aggregate`: the whole truth table runs in milliseconds under
`tests/test_evaluate_day.py`. Four of the five rules of the verdict live here.
The fifth is `verdict_override` — «день был выигран, просто я не отметил» — and
it is applied in `app.crud.summary.recompute_history`, because it is a fact of
the stored row rather than of the day's facts. It is one-directional: it turns
`lost` into `won` and never the reverse, and it leaves the reason this function
reached untouched.

Related: ADR-0014 (day in postgres), Р2 and Р8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.humanize import hours_and_minutes
from app.day.marks import TaskCounts
from app.models.day import DayRuleSet, role_clause_roles

__all__ = [
    "DEFAULT_REASON_ORDER",
    "REASON_ROLE_ACT",
    "Clause",
    "role_clause_applies",
    "MISSING_ANCHOR_KINDS",
    "MISSING_WORK_MINUTES",
    "REASON_ANCHORS",
    "REASON_NONE",
    "REASON_NOT_CLOSED",
    "REASON_OVERTIME",
    "REASON_TASKS",
    "VERDICT_LOST",
    "VERDICT_WON",
    "VERDICTS",
    "DayFacts",
    "UnknownVerdictReason",
    "Verdict",
    "evaluate_day",
    "verdict_reasons",
]

# The two things a verdict can say. Absence of a verdict — the day nobody
# closed — is `None` and deliberately not a third word: it is not a judgement.
VERDICT_WON = "won"
VERDICT_LOST = "lost"
VERDICTS: tuple[str, ...] = (VERDICT_WON, VERDICT_LOST)

# Which condition was not met, machine-readable. The Russian a person reads is
# a label in `lib/day-format.ts`, the same way `mark.state` is handled: one
# vocabulary in the database, one translation on the screen.
REASON_NONE = ""
REASON_NOT_CLOSED = "not_closed"
REASON_OVERTIME = "overtime"
REASON_ANCHORS = "anchors"
REASON_TASKS = "tasks"
# Клауз роли (`#137`). Не входит в `verdict_rule.reason_order` и не может: он
# включается своей парой полей строки правила, потому что вместе с «считать ли»
# у него есть «какие роли считать», а порядок условий такого второго значения
# не носит.
REASON_ROLE_ACT = "role_act"

# What the day could not be judged on. `work_minutes` is measured by nothing
# until `#91`; `anchor_kinds` — which anchors of the canon the day actually
# closed — until the plan names them or `day_anchor` arrives with `#92`.
MISSING_WORK_MINUTES = "work_minutes"
MISSING_ANCHOR_KINDS = "anchor_kinds"

# The order the conditions are weighed in when the rule row does not say. The
# priority of `config.md`: работа сначала (переработка снимает день целиком),
# затем якоря здоровья и отношений, затем задачи.
DEFAULT_REASON_ORDER: tuple[str, ...] = (REASON_OVERTIME, REASON_ANCHORS, REASON_TASKS)

# Key of `verdict_rule` the order is written under.
REASON_ORDER_KEY = "reason_order"

# Что означает `kind` рабочего дня. Продублировано из `app.day.rules` намеренно:
# импорт оттуда сюда закольцевал бы модули — `rules` уже импортирует `evaluate`.
KIND_WORK = "work"


class UnknownVerdictReason(ValueError):
    """
    `verdict_rule.reason_order` names a condition nothing knows how to weigh.

    Loud rather than ignored. A silently dropped code would mean a canon a
    person wrote — «перестань снимать день за задачи» — applied in a way nobody
    asked for, and the whole point of keeping the formula in a row is that what
    is written there is what happens.
    """


def verdict_reasons(rule: DayRuleSet) -> tuple[str, ...]:
    """
    Which conditions lower a day under this canon, in the order they are weighed.

    A row with no formula — one built in memory, or written before `#142` — is
    judged by `DEFAULT_REASON_ORDER`: that is the canon as it stood, and reading
    an absent column as "ничто не снимает день" would silently turn every past
    day into a won one.
    """
    formula = rule.verdict_rule or {}
    raw = formula.get(REASON_ORDER_KEY)
    if raw is None:
        return DEFAULT_REASON_ORDER
    if not isinstance(raw, list):
        raise UnknownVerdictReason(
            f"verdict_rule.{REASON_ORDER_KEY} правила {rule.id} — не список: "
            f"{raw!r}. Формула вердикта это порядок условий, а не одно значение."
        )
    order = tuple(str(reason) for reason in raw)
    unknown = [reason for reason in order if reason not in DEFAULT_REASON_ORDER]
    if unknown:
        raise UnknownVerdictReason(
            f"verdict_rule.{REASON_ORDER_KEY} правила {rule.id} называет условия "
            f"{unknown}, которых нет: считать можно "
            f"{list(DEFAULT_REASON_ORDER)}. Опечатка в правиле молча не "
            "проглатывается — иначе день считался бы не по тому, что записано."
        )
    return order


@dataclass(frozen=True)
class RoleActFact:
    """
    Один акт роли, закрытый в этот день.

    Код роли и её название приезжают вместе: код решает клауз, название читает
    человек. Название берётся из справочника, а не собирается здесь по коду, —
    роль можно переименовать, и расшифровка, отставшая от справочника, называла
    бы человеку роль, которой у него больше нет.
    """

    role_code: str
    role_title: str
    act_kind: str
    title: str


@dataclass(frozen=True)
class Clause:
    """
    Одно условие канона и его исход.

    `detail` — не украшение и не подпись к коду: человек, увидевший «условие не
    выполнено», не знает, что делать дальше, а увидевший «ни одного акта CTO или
    архитектора» — знает. Строка собирается там же, где условие взвешивается,
    потому что второе описание того же условия разошлось бы с первым.
    """

    code: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DayFacts:
    """
    Everything the verdict is decided from, as plain values.

    Assembled by `app.crud.summary` out of rows that already exist: the marks of
    the plan for both counters, and `work_minutes` from the day's `work_interval`
    rows (`#91`). A day with no intervals falls back to the number `POST /close`
    carried, and to `None` when it carried none either.
    """

    closed: bool
    tasks: TaskCounts
    anchors: TaskCounts
    work_minutes: int | None
    # Which anchors of the canon the day actually closed, by kind. `None` means
    # «состав не измерен», not «ни одного»: the plan of the day names its
    # anchors only when its lines carry codes, and the catalogue that will
    # always name them (`day_anchor`) arrives with `#92`. An unmeasured
    # composition falls back to the counter and says so in `missing_data`,
    # exactly as an unmeasured `work_minutes` does.
    anchor_kinds: frozenset[str] | None = None
    # Чем день был по календарю канона в момент своего создания (`#86`).
    # `None` — «неизвестно»: у импортированного дня строки `day` может не быть
    # вовсе, и клауз роли к такому дню не применяется, потому что применять его
    # не к чему.
    day_kind: str | None = None
    is_nocode: bool = False
    # Акты роли, закрытые в этот день. Пустой кортеж — «ни одного», а не «не
    # измерено»: с `#134` таблица `role_act` есть всегда, и день без строк — это
    # день без актов.
    role_acts: tuple[RoleActFact, ...] = ()
    # Названия ролей клауза по коду — для расшифровки непройденного клауза, у
    # которого актов нет и взять название неоткуда.
    role_titles: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    """
    The judgement of one day, and everything it was reached from.

    Carries `rule_set_id` because "по какому правилу считался этот день" is part
    of the answer, not context around it: the canon changed on 2026-08-17, and a
    verdict without the rule it was measured against cannot be re-read a month
    later.
    """

    verdict: str | None
    reason: str
    rule_set_id: int
    anchors_done: int
    anchors_total: int
    tasks_done: int
    tasks_total: int
    work_minutes: int | None
    missing_data: tuple[str, ...]
    # Anchors of the canon the day did not close, by kind — empty when the
    # composition was not measured. Named rather than counted: «не хватило
    # вечера с близкими» is what a reader can act on, «якоря 5/6» is not.
    missing_anchor_kinds: tuple[str, ...] = ()
    # Все условия канона, взвешенные для этого дня, в порядке взвешивания.
    # Вердикт выведен из них, а не сосчитан рядом: `reason` — код первого
    # непройденного, `verdict` — «непройденных нет».
    clauses: tuple[Clause, ...] = ()


def _closed_of(counts: TaskCounts) -> tuple[int, int]:
    """
    How many lines were closed, of how many that still counted.

    `skipped` leaves the denominator — the rule is written once, in
    `app.day.marks`, and this is the only reading of it under which «3 из 3»
    after a cancelled meeting is not a lie in either direction.
    """
    return counts.done, counts.planned - counts.skipped


def _tasks_are_short(rule: DayRuleSet, done: int, total: int) -> bool:
    """Whether the share of closed tasks is under the bar of the rule."""
    if total == 0:
        return False
    return Decimal(done) / Decimal(total) < rule.tasks_required_ratio


def _anchors_not_closed(rule: DayRuleSet, facts: DayFacts) -> tuple[str, ...]:
    """
    Which anchors of the canon the day left open, by kind.

    The composition comes from the row (`anchors`), so adding «вечер с
    близкими» to the canon is an INSERT rather than an edit of this function —
    and a day lived under the older row keeps being judged by the five anchors
    it was lived under. An unmeasured composition answers with nothing at all;
    the counter of the plan's own anchor lines still has the last word.
    """
    if facts.anchor_kinds is None:
        return ()
    closed = facts.anchor_kinds
    return tuple(kind for kind in (rule.anchors or ()) if kind not in closed)


def role_clause_applies(rule: DayRuleSet, facts: DayFacts) -> bool:
    """
    Судится ли этот день клаузом роли.

    Три условия, и каждое ломается по-своему. Канон не включал клауз — день
    прожит правилом, при котором ролей не измеряли, и требовать акт задним
    числом значило бы снимать день за то, чего нельзя было записать. День
    нерабочий — акта роли в выходной никто не ждёт. День no-code — он учебный,
    и его смысл не в актах должности.

    `day_kind is None` — «строки дня нет»: импортированная история, у которой
    материализованного вида дня не было никогда. Клауз к такому дню не
    применяется, потому что применять его не к чему.
    """
    if not rule.role_clause_enabled:
        return False
    if facts.is_nocode:
        return False
    return facts.day_kind == KIND_WORK


def _acts_of_clause(rule: DayRuleSet, facts: DayFacts) -> tuple[RoleActFact, ...]:
    """Акты дня, засчитываемые клаузом, — по кодам ролей строки правила."""
    wanted = set(role_clause_roles(rule.role_clause_roles))
    return tuple(act for act in facts.role_acts if act.role_code in wanted)


def _role_names(rule: DayRuleSet, facts: DayFacts) -> str:
    """Роли клауза словами: «CTO или архитектора»."""
    codes = role_clause_roles(rule.role_clause_roles)
    names = [facts.role_titles.get(code, code) for code in codes]
    if not names:
        return "нужной роли"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} или {names[-1]}"


def _role_clause(rule: DayRuleSet, facts: DayFacts) -> Clause:
    """
    Клауз роли: закрыт ли за день хотя бы один акт роли, отличной от тимлида.

    Расшифровка называет роль и акт, а не «условие не выполнено»: человек,
    прочитавший «архитектор: 1 акт (ADR-0020)», знает, чем день закрыт, а
    прочитавший «ни одного акта CTO или архитектора» — знает, что делать.
    """
    matched = _acts_of_clause(rule, facts)
    if not matched:
        return Clause(
            code=REASON_ROLE_ACT,
            passed=False,
            detail=f"ни одного акта {_role_names(rule, facts)}",
        )
    by_role: dict[str, list[RoleActFact]] = {}
    for act in matched:
        by_role.setdefault(act.role_title, []).append(act)
    parts = [
        f"{title}: {len(acts)} акт(ов) ({acts[0].title})"
        for title, acts in by_role.items()
    ]
    return Clause(code=REASON_ROLE_ACT, passed=True, detail="; ".join(parts))


def _overtime_clause(
    rule: DayRuleSet, facts: DayFacts, work_cap_min: int | None = None
) -> Clause:
    """
    Переработка: сравнение с обычным потолком, а не с исключением.

    Потолок берётся у профиля, действовавшего на этой дате (`#179`), а строка
    правила отвечает, когда профиль ничего не сказал: день, прожитый до
    профилей, или день, который не накрыла ни одна активация. Жёсткий потолок
    (`work_hard_cap_min`) здесь по-прежнему ни при чём — это исключение, за
    которым день имеет право потянуться, а не линия, по которой его судят.
    """
    if facts.work_minutes is None:
        return Clause(REASON_OVERTIME, True, "работа не измерена")
    if not rule.overtime_disqualifies:
        return Clause(
            REASON_OVERTIME,
            True,
            f"{hours_and_minutes(facts.work_minutes)}, потолок не судит",
        )
    cap = work_cap_min if work_cap_min is not None else rule.work_cap_min
    return Clause(
        code=REASON_OVERTIME,
        passed=facts.work_minutes <= cap,
        detail=f"{hours_and_minutes(facts.work_minutes)} при потолке {hours_and_minutes(cap)}",
    )


def _anchors_clause(done: int, total: int, missing_kinds: tuple[str, ...]) -> Clause:
    """Якоря: закрыты ли все, вписанные в план этого дня, и какие остались."""
    passed = done >= total and not missing_kinds
    detail = f"якоря {done}/{total}"
    if missing_kinds:
        detail = f"{detail}, не закрыты: {', '.join(missing_kinds)}"
    return Clause(code=REASON_ANCHORS, passed=passed, detail=detail)


def _tasks_clause(rule: DayRuleSet, done: int, total: int) -> Clause:
    """Задачи: доля закрытых против планки канона."""
    return Clause(
        code=REASON_TASKS,
        passed=not _tasks_are_short(rule, done, total),
        detail=f"задачи {done}/{total} при планке {rule.tasks_required_ratio}",
    )


def evaluate_day(
    rule: DayRuleSet, facts: DayFacts, *, work_cap_min: int | None = None
) -> Verdict:
    """
    Judge one day against the canon it was lived under.

    Returns the verdict, the condition that was not met, and the counters the
    screen shows — so that a reader is never told only "день не выигран" and
    left to guess which of three things went wrong.

    `anchors_done < anchors_total` reads as «закрыты все якоря, вписанные в этот
    план», not «закрыты все пять якорей канона»: `rule.required_anchors` is
    deliberately not consulted, and a plan without a single anchor line gives
    0/0 and passes. The reasoning is in the module docstring; `#92` is where it
    changes.

    Which conditions are weighed, and in which order, is `verdict_rule` of the
    same row: this function knows how to weigh each condition, and the row says
    which of them count. That is why a change of canon — «якоря больше не
    снимают день», «добавился шестой якорь» — is a new row and never a patch
    here.
    """
    anchors_done, anchors_total = _closed_of(facts.anchors)
    tasks_done, tasks_total = _closed_of(facts.tasks)
    missing_anchor_kinds = _anchors_not_closed(rule, facts)

    missing_data: tuple[str, ...] = ()
    if facts.work_minutes is None:
        missing_data += (MISSING_WORK_MINUTES,)
    # Only worth saying when the canon actually names anchors: a row that names
    # none has nothing to measure, and reporting a gap there would be noise
    # rather than a fact.
    if facts.anchor_kinds is None and rule.anchors:
        missing_data += (MISSING_ANCHOR_KINDS,)

    built = {
        REASON_OVERTIME: lambda: _overtime_clause(rule, facts, work_cap_min),
        REASON_ANCHORS: lambda: _anchors_clause(
            anchors_done, anchors_total, missing_anchor_kinds
        ),
        REASON_TASKS: lambda: _tasks_clause(rule, tasks_done, tasks_total),
    }
    clauses = tuple(built[reason]() for reason in verdict_reasons(rule))
    # Клауз роли стоит последним: день, сорванный переработкой или якорями,
    # решается ими, а не отсутствием акта — иначе человека отправили бы чинить
    # не то, что сломалось.
    if role_clause_applies(rule, facts):
        clauses += (_role_clause(rule, facts),)

    def decided(verdict: str | None, reason: str) -> Verdict:
        return Verdict(
            verdict=verdict,
            reason=reason,
            rule_set_id=rule.id,
            anchors_done=anchors_done,
            anchors_total=anchors_total,
            tasks_done=tasks_done,
            tasks_total=tasks_total,
            work_minutes=facts.work_minutes,
            missing_data=missing_data,
            missing_anchor_kinds=missing_anchor_kinds,
            clauses=clauses,
        )

    # Не судить нечего: день, который никто не закрыл, вердикта не получает —
    # и это не условие формулы, а её отсутствие. Клаузы при этом посчитаны и
    # отданы: экран показывает, что уже сходится, до того как день закрыт.
    if not facts.closed:
        return decided(None, REASON_NOT_CLOSED)

    failed = [clause for clause in clauses if not clause.passed]
    if failed:
        return decided(VERDICT_LOST, failed[0].code)
    return decided(VERDICT_WON, REASON_NONE)
