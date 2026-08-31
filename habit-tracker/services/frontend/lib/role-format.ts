// [review:need-review] PHASE-03/134, PHASE-03/135
// summary: pure labels for the role screen — the act vocabulary in Russian, the target share always printed with the word «гипотеза», the day's roles read as «архитектор — 1 акт» or as «актов роли сегодня нет», the mark that says a record was typed by a person, the mark that says one was computed by the markup with the rule and application behind it, and the share of the day nothing could be attributed to

import type { RoleAct, RoleDay, RoleDaySlice, RoleTimeBlock } from '@/lib/api';
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

/** Mark on a record the markup of `#135` computed from measured activity. */
export const AUTOMATIC_MARK = 'автоматически';

/** Label of the button that freezes an automatic record against the next run. */
export const CONFIRM_LABEL = 'подтвердить';

/** Mark on a record a person has confirmed; the markup no longer touches it. */
export const CONFIRMED_MARK = 'подтверждено';

/** The code of the role work that could not be attributed is charged to. */
export const UNASSIGNED_CODE = 'unassigned';

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

/**
 * Why an automatic record says what it says, or null when it is not automatic.
 *
 * The rule and the application, both of them, because they answer different
 * halves of «почему эти два часа — тимлид»: the rule is the decision, the
 * application is what it was applied to. A record whose rule has since been
 * deleted still names its application, which is more than nothing.
 */
export function markupSource(block: RoleTimeBlock): string | null {
  if (!block.is_automatic) return null;
  const parts = [block.app_name, block.rule_summary].filter(
    (part): part is string => Boolean(part)
  );
  if (parts.length === 0) return AUTOMATIC_MARK;
  return `${AUTOMATIC_MARK}: ${parts.join(' · ')}`;
}

/**
 * The share of the day nothing could be attributed to, as a line, or null.
 *
 * A number rather than a silence. «Не удалось отнести» is a fact worth seeing —
 * it is the number that says the rules need another line — and a screen that
 * showed only the three roles that matched would hide exactly that.
 */
export function unassignedLine(day: RoleDay): string | null {
  const slice = day.roles.find((row) => row.role_code === UNASSIGNED_CODE);
  if (!slice || slice.minutes === 0) return null;
  return `не отнесено: ${slice.share_pct}%`;
}

/** One act as the line the screen prints. */
export function actLine(act: RoleAct): string {
  return `${actKindLabel(act.act_kind)}: ${act.title}`;
}
