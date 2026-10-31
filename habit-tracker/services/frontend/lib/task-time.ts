// [review:need-review] PHASE-03/166
// summary: pure helpers of the task-time blocks — minutes per plan item as a map, the caption of the thirty-day untasked share that names the days really observed instead of passing a short window off as a month, and the wording of the «done, no trace» note that tells whether commits were looked at
import type { TaskTimeDay, UntaskedShare } from '@/lib/api';
import { countable } from '@/lib/plural';

export const DONE_NO_TRACE_TITLE = 'Отмечено сделанным, следов нет';
export const LONG_UNTASKED_TITLE = 'Работа вне плана';
export const SHARE_TITLE = 'Интервалы без задачи';
export const OTHER_LINKED_TITLE = 'Привязано не к задаче плана';
export const OTHER_LINKED_NOTE =
  'Интервалы с номером задачи или ClickUp-задачей: это не пункт плана и не «без задачи».';

const PERCENT = 100;

/** Minutes by plan item id, for the badge beside each task of the plan. */
export function minutesByItem(taskTime: TaskTimeDay | null): Map<string, number> {
  return new Map((taskTime?.tasks ?? []).map((row) => [row.plan_item_id, row.minutes]));
}

/** The share as a whole percent: «62%». */
export function sharePercent(share: UntaskedShare): string | null {
  return share.share === null ? null : `${Math.round(share.share * PERCENT)}%`;
}

/**
 * What the share was measured over.
 *
 * A window that is not full says how many days it covers: a number over three
 * days of data is a three-day number, and calling it monthly is the lie this
 * caption exists to prevent.
 */
export function shareWindowCaption(share: UntaskedShare): string {
  if (share.observed_days >= share.window_days) {
    return `за ${countable(share.window_days, 'день', 'дня', 'дней')}`;
  }
  return `за ${countable(share.observed_days, 'день', 'дня', 'дней')} данных из ${share.window_days}`;
}

/** Why the list may be shorter than the truth: the web never sees git. */
export function doneNoTraceNote(commitsChecked: boolean): string {
  return commitsChecked
    ? 'Ни интервала, ни коммита по этим задачам нет.'
    : 'Интервалов по этим задачам нет. Коммиты здесь не видны — их смотрит закрытие дня.';
}

/** Whether the summary has anything to say; an empty one draws nothing. */
export function hasTaskTimeSummary(taskTime: TaskTimeDay | null): boolean {
  if (taskTime === null) return false;
  return (
    taskTime.done_without_traces.length > 0 ||
    taskTime.long_untasked.length > 0 ||
    taskTime.other_linked_minutes > 0 ||
    taskTime.untasked_share.intervals > 0
  );
}

/**
 * A string that changes when the set of done marks does, or null while a mark is
 * being written. The list of «done, no trace» is read again on each change;
 * `useTaskTime` keeps the last settled key through a null, so the read happens
 * once after the write and not in parallel with it.
 */
export function doneMarksKey(
  marks: Map<string, { state: string | null }>,
  saving: Set<string>
): string | null {
  if (saving.size > 0) return null;
  return [...marks.entries()]
    .filter(([, mark]) => mark.state === 'done')
    .map(([id]) => id)
    .sort()
    .join(',');
}
