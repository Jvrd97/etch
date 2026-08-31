// [review:need-review] PHASE-03/134
// summary: pure labels for the role screen — the act vocabulary in Russian, the target share always printed with the word «гипотеза», the day's roles read as «архитектор — 1 акт» or as «актов роли сегодня нет», and the mark that says a record was typed by a person

import type { RoleAct, RoleDay, RoleDaySlice } from '@/lib/api';
import { countable } from '@/lib/plural';

/**
 * What the target share is, said out loud wherever it is shown.
 *
 * Not decoration. The share is a guess about a quarter that has never been
 * measured, and a number printed beside a measurement reads as a norm unless
 * something says otherwise — after which the temptation is to fit the markup to
 * the number instead of the day.
 */
export const TARGET_SHARE_HYPOTHESIS = 'гипотеза, не норма';

/** Shown where a day carries no acts at all. */
export const NO_ACTS_TEXT = 'Актов роли сегодня нет';

/** Shown where a day carries no minutes at all. */
export const NO_MINUTES_TEXT = 'Минут за день пока не записано';

/** Mark on a record a person typed, as opposed to one an importer computed. */
export const MANUAL_MARK = 'вручную';

/** Shown when the day cannot be read at all. */
export const LOAD_ROLES_ERROR = 'Не удалось загрузить роли';

/** The act vocabulary in Russian; the codes stay in the database. */
const ACT_KIND_LABELS: Record<string, string> = {
  adr_written: 'написан ADR',
  data_model_decision: 'решение по модели данных',
  security_review: 'ревью безопасности',
  roadmap_update: 'правка роадмапа',
  budget_decision: 'решение по бюджету',
  hiring_step: 'шаг по найму',
  report_to_management: 'отчёт руководству',
  partner_talk: 'разговор с партнёром',
  code_review: 'code review',
  ci_change: 'правка CI',
  wrote_from_scratch: 'написано с нуля',
};

/** Every kind the form offers, in the order it offers them. */
export const ACT_KIND_OPTIONS: readonly { value: string; label: string }[] =
  Object.entries(ACT_KIND_LABELS).map(([value, label]) => ({ value, label }));

/**
 * Human name of an act kind, falling back to the code.
 *
 * The vocabulary lives in the backend schema and grows there; a kind this map
 * has not caught up with shows its code rather than disappearing from the day.
 */
export function actKindLabel(kind: string): string {
  return ACT_KIND_LABELS[kind] ?? kind;
}

/**
 * The target share as a line, or null when the role has no target.
 *
 * The word «гипотеза» is part of the string rather than a nearby caption on
 * purpose: a caption can be scrolled away from the number it qualifies.
 */
export function targetShareLine(slice: RoleDaySlice): string | null {
  if (slice.target_share_pct === null) return null;
  return `цель ${slice.target_share_pct}% — ${TARGET_SHARE_HYPOTHESIS}`;
}

/** `1 акт` / `2 акта` / `5 актов`. */
export function actsCount(count: number): string {
  return countable(count, 'акт', 'акта', 'актов');
}

/**
 * What happened to the roles today, in one line.
 *
 * Names only the roles that actually carry an act, because that is the question
 * — «роль сегодня случилась?» — and a list of four roles with three zeroes
 * answers it worse than a sentence naming the one that did.
 */
export function actsSummary(day: RoleDay): string {
  const withActs = day.roles.filter((slice) => slice.act_count > 0);
  if (withActs.length === 0) return NO_ACTS_TEXT;
  return withActs
    .map((slice) => `${slice.title} — ${actsCount(slice.act_count)}`)
    .join(', ');
}

/** One act as the line the screen prints. */
export function actLine(act: RoleAct): string {
  return `${actKindLabel(act.act_kind)}: ${act.title}`;
}
