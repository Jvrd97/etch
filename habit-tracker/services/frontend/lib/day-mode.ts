// [review:need-review] PHASE-03/228
// summary: the words of the day mode on screen — a label per kind, who decided (schedule or hand), the week in the order a person reads it (Monday first) over the server's 0 = Sunday numbering

import type { DayMode, DayModeKind } from '@/lib/api';

export const KIND_OPTIONS: { value: DayModeKind; label: string }[] = [
  { value: 'work', label: 'Рабочий' },
  { value: 'dayoff', label: 'Выходной' },
  { value: 'vacation', label: 'Отпуск' },
  { value: 'sick', label: 'Болезнь' },
];

export const NOCODE_LABEL = 'no-code';
export const RESET_LABEL = 'Вернуть к расписанию';

/** «По расписанию» and «вручную» are the same day and two different facts. */
export function sourceLabel(source: DayMode['source']): string {
  return source === 'manual' ? 'вручную' : 'по расписанию';
}

/** Server weekday numbers (0 = Sunday) in the order a week is read, Monday first. */
export const WEEK_ORDER: { weekday: number; label: string }[] = [
  { weekday: 1, label: 'Понедельник' },
  { weekday: 2, label: 'Вторник' },
  { weekday: 3, label: 'Среда' },
  { weekday: 4, label: 'Четверг' },
  { weekday: 5, label: 'Пятница' },
  { weekday: 6, label: 'Суббота' },
  { weekday: 0, label: 'Воскресенье' },
];
