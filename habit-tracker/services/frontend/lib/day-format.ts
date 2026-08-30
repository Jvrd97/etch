// [review:need-review] PHASE-03/86, PHASE-03/90, PHASE-03/142
// summary: pure labels for the day screen — what kind of day it is, the plain-Russian reading of the rule it is judged by, the map of the day that rule draws (edges, free evening, evening with the family, the formula of the verdict), and the verdict itself with the condition it failed on, what could not be measured and the streak in countable Russian (both shells render the same strings)

import type {
  Day,
  DayMap,
  DayRuleSet,
  VerdictReason,
  MissingData,
} from '@/lib/api';

/** Text shown where a plan would be. A day without one is an answer, not an error. */
export const NO_PLAN_TEXT = 'Плана нет';

/** Why there is nothing to show — said out loud, so the screen never looks broken. */
export const NO_PLAN_HINT =
  'На этот день план ещё не собран. Дата, вид дня и правило уже есть — плана нет.';

/** Shown while the day is still loading and nothing can be said about it yet. */
export const LOAD_DAY_ERROR = 'Не удалось загрузить день';

const WEEKDAY_NAMES = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];

const MINUTES_PER_HOUR = 60;

/** Human label of a day's kind. */
export function dayKindLabel(day: Day): string {
  return day.kind === 'work' ? 'рабочий день' : 'выходной';
}

/** Weekday names for ISO numbers (1 = Monday), in week order, without repeats. */
export function weekdayNames(isoNumbers: number[]): string[] {
  const seen = new Set(isoNumbers);
  return WEEKDAY_NAMES.filter((_, index) => seen.has(index + 1));
}

/** Minutes as "8 ч" / "8 ч 30 мин" — the way the canon itself is written. */
export function formatMinutes(minutes: number): string {
  const whole = Math.max(0, Math.round(minutes));
  const hours = Math.floor(whole / MINUTES_PER_HOUR);
  const rest = whole % MINUTES_PER_HOUR;
  if (hours === 0) return `${rest} мин`;
  if (rest === 0) return `${hours} ч`;
  return `${hours} ч ${rest} мин`;
}

/** `HH:MM:SS` from the API trimmed to the `HH:MM` a human reads. */
export function formatClock(time: string): string {
  return time.slice(0, 5);
}

/** `0.80` as `80%` — the share of tasks that has to be closed. */
export function formatRatio(ratio: string): string {
  const value = Number(ratio);
  if (!Number.isFinite(value)) return ratio;
  return `${Math.round(value * 100)}%`;
}

/** One line of the rule: what it constrains and what the number is. */
export interface RuleLine {
  label: string;
  value: string;
}

/**
 * The rule read out in plain Russian.
 *
 * The screen shows this rather than the raw row because the point of a
 * versioned canon is that the reader can see *which* numbers this particular
 * day is judged by — the 14th and the 30th are not judged by the same ones.
 */
export function ruleLines(rule: DayRuleSet): RuleLine[] {
  return [
    { label: 'Работа', value: `${formatMinutes(rule.work_cap_min)} в день` },
    {
      label: 'Потолок-исключение',
      value: formatMinutes(rule.work_hard_cap_min),
    },
    { label: 'Стоп', value: formatClock(rule.work_stop_at) },
    { label: 'Рабочих задач', value: `не больше ${rule.max_work_tasks}` },
    {
      label: 'Закрыть задач',
      value: formatRatio(rule.tasks_required_ratio),
    },
    {
      label: 'Переработка',
      value: rule.overtime_disqualifies
        ? 'день не выигран'
        : 'на вердикт не влияет',
    },
    { label: 'Рабочие дни', value: weekdayNames(rule.workdays).join(', ') },
    {
      label: 'No-code дни',
      value: weekdayNames(rule.nocode_days).join(', ') || 'нет',
    },
    {
      label: 'Сутки',
      value: `${rule.timezone}, с ${String(rule.day_start_hour).padStart(2, '0')}:00`,
    },
  ];
}

/**
 * Since when — and until when — this rule applies.
 *
 * Spelled out because it is the answer to "why is this day counted like that":
 * an interval, not a constant somebody could have edited yesterday.
 */
export function ruleValidity(rule: DayRuleSet): string {
  if (rule.valid_to === null) return `действует с ${rule.valid_from}`;
  return `действовало с ${rule.valid_from} по ${rule.valid_to}`;
}

/**
 * What the verdict says, including its absence.
 *
 * `null` is не «проиграл» а «не закрыт» — the distinction the whole slice
 * exists to keep: nobody has said what happened to the day yet.
 */
export function verdictLabel(verdict: 'won' | 'lost' | null): string {
  if (verdict === 'won') return 'День выигран';
  if (verdict === 'lost') return 'День проигран';
  return 'День не закрыт';
}

/**
 * Which condition was not met, in one word.
 *
 * The server sends a code and the screen translates it, the way it does for
 * `mark.state`. A reader told only «день не выигран» has to guess which of
 * three things to repair, and that guess is what the ticket removes.
 */
const REASON_LABEL: Record<VerdictReason, string> = {
  tasks: 'задачи',
  anchors: 'якоря',
  overtime: 'переработка',
  not_closed: 'день не закрыт',
};

export function verdictReasonLabel(reason: VerdictReason | ''): string {
  return reason === '' ? '' : REASON_LABEL[reason];
}

/** What the day could not be judged on — «не измерено», а не «ноль». */
const MISSING_LABEL: Record<MissingData, string> = {
  work_minutes: 'время не измерено',
  anchor_kinds: 'состав якорей не измерен',
};

export function missingDataLabel(code: MissingData): string {
  return MISSING_LABEL[code];
}

/**
 * A streak of days, counted the way Russian counts.
 *
 * «1 день», «2 дня», «5 дней» — and 11 to 14 are «дней» however they end,
 * which is exactly the case a naive `n % 10` gets wrong.
 */
export function streakLabel(days: number): string {
  const lastTwo = days % 100;
  const last = days % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return `${days} дней`;
  if (last === 1) return `${days} день`;
  if (last >= 2 && last <= 4) return `${days} дня`;
  return `${days} дней`;
}

/** Shown against an edge the canon places but does not clock. */
export const EDGE_WITHOUT_A_TIME = 'часа в каноне нет';

/** One line of the map of the day: the edge and the hour it stands at. */
export interface EdgeLine {
  kind: string;
  label: string;
  value: string;
}

/**
 * The hard edges of the day, in the order the canon lists them.
 *
 * The hours are the server's — `06:00`, `15:40`, `22:30` are columns of the
 * rule row, and the whole point of `#142` is that they are nowhere in this
 * file. Спорт has no hour and says so, instead of being given an invented one.
 */
export function edgeLines(map: DayMap): EdgeLine[] {
  return map.edges.map((edge) => ({
    kind: edge.kind,
    label: edge.label,
    value: edge.at === null ? EDGE_WITHOUT_A_TIME : formatClock(edge.at),
  }));
}

/** `19:10-21:00` — the block of the evening a plan may not fill. */
export function intervalText(interval: { start: string; end: string }): string {
  return `${formatClock(interval.start)}-${formatClock(interval.end)}`;
}

/**
 * What the free evening is, said out loud beside its hours.
 *
 * «Свободный блок — награда, а не обязанность»: the sentence exists on the
 * screen because an empty stretch of the plan otherwise reads as a hole
 * somebody forgot to fill.
 */
export const FREE_EVENING_HINT = 'не расписывается — награда, а не обязанность';

/** Whether the evening with the family is required, in plain Russian. */
export function relationshipEveningText(map: DayMap): string {
  if (!map.relationship_anchor_required) return 'не требуется этим каноном';
  return `${intervalText(map.relationship_evening)} — вечер с близкими`;
}

/**
 * The formula of the verdict, in the order the server weighs it.
 *
 * Reading it on the page is what makes «по какому правилу этот день считается»
 * answerable without opening the database: the order is a column, and a canon
 * that stops lowering the day for anchors shows it here.
 */
export function verdictFormulaText(map: DayMap): string {
  if (map.verdict_reasons.length === 0) return 'ничто не снимает день';
  return map.verdict_reasons.map(verdictReasonLabel).join(' → ');
}
