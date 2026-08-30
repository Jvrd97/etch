// [review:need-review] PHASE-03/86
// summary: pure labels for the day screen — what kind of day it is, and the plain-Russian reading of the rule it is judged by (both shells render the same strings)

import type { Day, DayRuleSet } from '@/lib/api';

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
