// [review:need-review] PHASE-03/160
// summary: pure readings of a day of activity — the clock of an interval, the mark on one a person corrected, «заголовок скрыт правилом» instead of an empty cell, the line of a manual record with no application, and the rule that the totals on screen are the server's numbers rather than a sum of the rows drawn

import type { ActivityDay, ActivityInterval } from '@/lib/api';
import { formatMinutes } from '@/lib/day-format';

/** Mark on an interval whose ends a person moved. */
export const CORRECTED_MARK = 'исправлено';

/**
 * What is said where a window title is missing.
 *
 * Not an empty cell: «заголовка нет» and «правило его не пропустило» are
 * different facts, and only the second one has an address a person can go to
 * and change.
 */
export const TITLE_HIDDEN_TEXT = 'заголовок скрыт правилом';

/** Where that address is. */
export const TITLE_RULES_HREF = '/agent/title-rules';
export const TITLE_RULES_LINK_TEXT = 'правила';

/** What a manual record is called where an application name would go. */
export const MANUAL_SOURCE_TEXT = 'записано руками';

/** Heading of the block and of its three readings. */
export const DAY_ACTIVITY_TITLE = 'Где прошёл день';
export const APPS_TITLE = 'По приложениям';
export const TASKS_TITLE = 'По задачам';
export const TAPE_TITLE = 'Лента';

/** Shown where the day has no measured activity at all. */
export const EMPTY_ACTIVITY_TEXT = 'Активность за этот день не записана';

/** Label of the row that carries work outside any task. */
export const UNTASKED_LABEL = 'Без задачи';

/**
 * Why the untasked row matters, printed under it.
 *
 * The Payment-service evening of 28 August is the case: work over the plan was
 * discovered from the notebook at night instead of from the screen at the hour.
 */
export const UNTASKED_HINT = 'Работа вне плана — видно в тот же час, а не вечером.';

/** `"10:00-11:30"` — the wall clock of an interval in the reader's own zone. */
export function intervalClock(interval: ActivityInterval): string {
  return `${clock(interval.started_at)}-${clock(interval.ended_at)}`;
}

function clock(moment: string): string {
  const at = new Date(moment);
  const hours = String(at.getHours()).padStart(2, '0');
  const minutes = String(at.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

/** What an interval was: its application, or the fact that it was typed. */
export function intervalSource(interval: ActivityInterval): string {
  if (interval.source === 'manual') return MANUAL_SOURCE_TEXT;
  return interval.app_name ?? interval.bundle_id ?? MANUAL_SOURCE_TEXT;
}

/** Whether the title of this interval was removed by the privacy policy. */
export function titleIsHidden(interval: ActivityInterval): boolean {
  return interval.title_source === 'dropped';
}

/** How long an interval ran, as the screen prints it. */
export function intervalLength(interval: ActivityInterval): string {
  return formatMinutes(Math.round(interval.duration_seconds / SECONDS_PER_MINUTE));
}

const SECONDS_PER_MINUTE = 60;

/**
 * The name of a task in the roll-up.
 *
 * The board has no task titles here yet — the link to the day's tasks is `#166`
 * — so a task is named by the id that names it everywhere else, and a ClickUp
 * id is printed as itself.
 */
export function taskLabel(
  planTaskId: number | null,
  clickupTaskId: string | null
): string {
  if (clickupTaskId) return clickupTaskId;
  if (planTaskId !== null) return `задача ${planTaskId}`;
  return UNTASKED_LABEL;
}

/**
 * Total time per task, exactly as the server counted it.
 *
 * Deliberately not a sum over the drawn rows: overlapping records are allowed,
 * the server counts the union of ranges, and a browser adding the same rows up
 * would print a larger number beside the same list. One question, one answer.
 */
export function taskTotalMinutes(day: ActivityDay): number {
  return day.tasks.reduce((sum, row) => sum + row.minutes, 0);
}

/** Whether the day has any work outside a task at all. */
export function hasUntasked(day: ActivityDay): boolean {
  return day.untasked_minutes > 0;
}
