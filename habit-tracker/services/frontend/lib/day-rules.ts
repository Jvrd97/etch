// [review:need-review] PHASE-03/152
// summary: pure logic of the rules screen — the draft of a new version and the one sentence that says why it cannot be published yet, plus how a version of the canon reads against today (прожита / действует / выйдет)

import type { DayRuleSet, DayRuleSetPublish } from '@/lib/api';

/** Bounds the server also enforces; the screen refuses first so nothing round-trips. */
export const MIN_DAY_START_HOUR = 0;
export const MAX_DAY_START_HOUR = 23;
export const MINUTES_PER_DAY = 24 * 60;
export const MIN_WORK_TASKS = 1;
export const MAX_WORK_TASKS = 20;
export const MIN_RATIO_PERCENT = 0;
export const MAX_RATIO_PERCENT = 100;
export const ISO_MONDAY = 1;
export const ISO_SUNDAY = 7;

/** `1.00` is what the API speaks; `100` is what the form shows. */
const PERCENT = 100;
const RATIO_DECIMALS = 2;

/** `HH:MM` from an `<input type="time">`; the API wants `HH:MM:SS`. */
const CLOCK_RE = /^\d{1,2}:\d{2}$/;

/**
 * The form's state: strings, because that is what inputs hold.
 *
 * Kept apart from `DayRuleSetPublish` on purpose. A half-typed ceiling is not a
 * number and a half-typed list of weekdays is not an array; modelling the draft
 * as the payload would mean either refusing keystrokes or inventing values for
 * fields the person has not finished typing.
 */
export interface RuleDraft {
  validFrom: string;
  timezone: string;
  dayStartHour: string;
  workCapMin: string;
  workHardCapMin: string;
  workStopAt: string;
  maxWorkTasks: string;
  /** The task bar as a percentage — `100`, not `1.00`. */
  tasksRequiredPercent: string;
  overtimeDisqualifies: boolean;
  /** ISO weekday numbers, comma-separated: `1,2,3,4,5`. */
  workdays: string;
  nocodeDays: string;
  /** Anchors, comma-separated. */
  requiredAnchors: string;
  /** Судит ли новая версия рабочий день по акту роли (`#137`). */
  roleClauseEnabled: boolean;
  /** Коды ролей клауза через запятую. */
  roleClauseRoles: string;
  noteMd: string;
}

/** A draft that can be sent, or the first reason it cannot. */
export type DraftResult =
  | { ok: true; payload: DayRuleSetPublish }
  | { ok: false; error: string };

/**
 * The form pre-filled with the version in force.
 *
 * Prefilled rather than blank because a new version is an edit of the canon in
 * every case that matters — «стоп теперь в 17:00» leaves the other eleven
 * fields alone — and an empty form would make the person retype the canon to
 * change one number of it.
 */
export function draftFromRule(rule: DayRuleSet, validFrom: string): RuleDraft {
  return {
    validFrom,
    timezone: rule.timezone,
    dayStartHour: String(rule.day_start_hour),
    workCapMin: String(rule.work_cap_min),
    workHardCapMin: String(rule.work_hard_cap_min),
    workStopAt: rule.work_stop_at.slice(0, 5),
    maxWorkTasks: String(rule.max_work_tasks),
    tasksRequiredPercent: String(Math.round(Number(rule.tasks_required_ratio) * PERCENT)),
    overtimeDisqualifies: rule.overtime_disqualifies,
    workdays: rule.workdays.join(', '),
    nocodeDays: rule.nocode_days.join(', '),
    requiredAnchors: rule.required_anchors.join(', '),
    roleClauseEnabled: rule.role_clause_enabled,
    roleClauseRoles: rule.role_clause_roles,
    noteMd: rule.note_md,
  };
}

/** A whole number inside `[min, max]`, or null when the text is neither. */
function wholeNumber(text: string, min: number, max: number): number | null {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value >= min && value <= max ? value : null;
}

/** `1, 2, 4` as ISO weekday numbers, or null when any part is not one. */
export function parseWeekdays(text: string): number[] | null {
  const parts = text
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part !== '');
  const numbers: number[] = [];
  for (const part of parts) {
    const number = wholeNumber(part, ISO_MONDAY, ISO_SUNDAY);
    if (number === null) return null;
    if (numbers.includes(number)) return null;
    numbers.push(number);
  }
  return numbers;
}

/** Comma-separated anchors, trimmed, empties dropped. */
export function parseAnchors(text: string): string[] {
  return text
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part !== '');
}

/**
 * Why this draft cannot become a version yet, or null when it can.
 *
 * A copy of the server's bounds, and deliberately so: the server refuses these
 * anyway, but a 422 arriving after a publish is a worse way to learn that the
 * exception ceiling sits below the everyday one. The date rule is the one thing
 * the screen cannot decide on its own — `earliest` comes from the server, whose
 * day turns at the canon's own boundary hour rather than at the browser's
 * midnight.
 */
export function draftError(draft: RuleDraft, earliest: string): string | null {
  if (draft.validFrom === '') return 'Не выбрана дата, с которой действует новая версия.';
  if (draft.validFrom < earliest) {
    return `Новая версия может начинаться не раньше ${earliest}: по сегодняшнему и прошедшим дням вердикты уже посчитаны и не пересчитываются.`;
  }
  if (draft.timezone.trim() === '') return 'Не указана зона: по ней считается, какому дню принадлежит момент.';
  if (wholeNumber(draft.dayStartHour, MIN_DAY_START_HOUR, MAX_DAY_START_HOUR) === null) {
    return `Час начала суток — целое число от ${MIN_DAY_START_HOUR} до ${MAX_DAY_START_HOUR}.`;
  }

  const cap = wholeNumber(draft.workCapMin, 1, MINUTES_PER_DAY);
  const hardCap = wholeNumber(draft.workHardCapMin, 1, MINUTES_PER_DAY);
  if (cap === null || hardCap === null) {
    return `Потолок работы — целое число минут от 1 до ${MINUTES_PER_DAY}.`;
  }
  if (hardCap < cap) {
    return 'Потолок-исключение ниже обычного: исключение не бывает строже правила.';
  }
  if (!CLOCK_RE.test(draft.workStopAt.trim())) return 'Время стопа — ЧЧ:ММ.';
  if (wholeNumber(draft.maxWorkTasks, MIN_WORK_TASKS, MAX_WORK_TASKS) === null) {
    return `Рабочих задач — целое число от ${MIN_WORK_TASKS} до ${MAX_WORK_TASKS}.`;
  }
  if (
    wholeNumber(draft.tasksRequiredPercent, MIN_RATIO_PERCENT, MAX_RATIO_PERCENT) === null
  ) {
    return `Планка задач — целое число процентов от ${MIN_RATIO_PERCENT} до ${MAX_RATIO_PERCENT}.`;
  }
  if (parseWeekdays(draft.workdays) === null) {
    return 'Рабочие дни — номера по ISO через запятую, 1 (понедельник) … 7 (воскресенье), без повторов.';
  }
  if (parseWeekdays(draft.nocodeDays) === null) {
    return 'No-code дни — номера по ISO через запятую, 1 (понедельник) … 7 (воскресенье), без повторов.';
  }
  const anchors = parseAnchors(draft.requiredAnchors);
  if (new Set(anchors).size !== anchors.length) return 'Якорь назван дважды.';
  // Включённый клауз без ролей объявил бы проигранным каждый рабочий день, и
  // человек узнал бы об этом вечером, а не сейчас.
  if (draft.roleClauseEnabled && parseAnchors(draft.roleClauseRoles).length === 0) {
    return 'Клауз роли включён, но ни одна роль не названа: акт «никакой роли» закрыть нельзя.';
  }
  return null;
}

/**
 * The draft as the API's payload, or the reason it is not one yet.
 *
 * Parsing lives beside the checking so that a value can only be built from a
 * draft that passed them: two functions, one of which can produce a payload out
 * of unchecked text, is how a `NaN` reaches a `NOT NULL` column.
 */
export function draftToPayload(draft: RuleDraft, earliest: string): DraftResult {
  const error = draftError(draft, earliest);
  if (error !== null) return { ok: false, error };

  const percent = Number(draft.tasksRequiredPercent.trim());
  const [hours, minutes] = draft.workStopAt.trim().split(':');
  return {
    ok: true,
    payload: {
      valid_from: draft.validFrom,
      timezone: draft.timezone.trim(),
      day_start_hour: Number(draft.dayStartHour.trim()),
      work_cap_min: Number(draft.workCapMin.trim()),
      work_hard_cap_min: Number(draft.workHardCapMin.trim()),
      work_stop_at: `${hours.padStart(2, '0')}:${minutes}:00`,
      max_work_tasks: Number(draft.maxWorkTasks.trim()),
      tasks_required_ratio: (percent / PERCENT).toFixed(RATIO_DECIMALS),
      overtime_disqualifies: draft.overtimeDisqualifies,
      workdays: parseWeekdays(draft.workdays) ?? [],
      nocode_days: parseWeekdays(draft.nocodeDays) ?? [],
      required_anchors: parseAnchors(draft.requiredAnchors),
      role_clause_enabled: draft.roleClauseEnabled,
      role_clause_roles: draft.roleClauseRoles.trim(),
      note_md: draft.noteMd,
    },
  };
}

/** Where a version stands relative to today. */
export type RuleStanding = 'past' | 'current' | 'scheduled';

/**
 * Whether the version has already judged days, is judging them, or will.
 *
 * The screen needs the three apart because only the first is untouchable in the
 * strong sense: days lived under it carry its verdicts, and that is the whole
 * reason nothing here can be edited.
 */
export function ruleStanding(rule: DayRuleSet, today: string): RuleStanding {
  if (rule.valid_from > today) return 'scheduled';
  if (rule.valid_to !== null && rule.valid_to <= today) return 'past';
  return 'current';
}

const STANDING_LABEL: Record<RuleStanding, string> = {
  past: 'по этой версии дни уже прожиты',
  current: 'действует сейчас',
  scheduled: 'вступит в силу',
};

/** One-line label of a version's standing, as the history list shows it. */
export function ruleStandingLabel(standing: RuleStanding): string {
  return STANDING_LABEL[standing];
}
