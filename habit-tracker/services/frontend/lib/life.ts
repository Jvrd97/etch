// [review:need-review] PHASE-03/94
// summary: pure timeline helpers — the three states of a day square, the weeks-lived/weeks-left counter life.html showed, ISO week codes and bounds, and the year → month grouping the sidebar draws; no fetching and no React, so every rule here is testable in milliseconds

import type { DayListItem } from '@/lib/api';
import { fromISODate, toISODate } from '@/lib/date';

// Re-exported so the timeline imports its date helpers from one module; the
// definitions stay in `lib/date`, which is where every `YYYY-MM-DD` of this app
// is turned into a Date and back.
export { fromISODate, toISODate };

/**
 * What a square of the timeline says about a day.
 *
 * **Three states, not two.** `life.py` painted from a regular expression over
 * prose and could only tell «выигран» from «проигран»; a day nobody had closed
 * came out looking exactly like a day that was lost. Here `won`, `lost` and
 * `open` are three different answers, and `future` is the fourth — a date that
 * has not happened is not an empty record.
 */
export type DayStatus = 'won' | 'lost' | 'open' | 'empty' | 'future';

/** What each state means in Russian, for the legend and the tooltip. */
export const STATUS_LABEL: Record<DayStatus, string> = {
  won: 'день выигран',
  lost: 'день проигран',
  open: 'день не закрыт',
  empty: 'записи нет',
  future: 'ещё не наступил',
};

/** Default birth date of the counter — the same one `life.html` shipped with. */
export const DEFAULT_BIRTH = '2000-05-11';

/**
 * Default frame of the life grid, in years.
 *
 * Not a forecast: a ruler. It exists so the scale is visible, not so a date is
 * known, and `life.html` said as much under its grid.
 */
export const DEFAULT_TARGET_YEARS = 97;

/** Columns of the life grid: 53 is the most ISO weeks a year can have. */
export const WEEKS_PER_ROW = 53;

const DAY_MS = 86_400_000;
const DAYS_IN_WEEK = 7;

/** Mean length of a year in weeks — what turns a frame in years into weeks. */
const WEEKS_PER_YEAR = 52.1775;

/** Zero-padding width of the month, day and ISO week fields. */
const PAD = 2;

/** `d` moved by `days`, without touching the original. */
export function addDays(day: Date, days: number): Date {
  const moved = new Date(day);
  moved.setDate(moved.getDate() + days);
  return moved;
}

/** The Monday of the week `day` is in, at local midnight. */
export function startOfWeek(day: Date): Date {
  const monday = new Date(day);
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % DAYS_IN_WEEK));
  monday.setHours(0, 0, 0, 0);
  return monday;
}

/**
 * The ISO week code of a date — `2026-W35`, the key the API uses.
 *
 * The Thursday rule: a week belongs to the year that owns its Thursday, which
 * is why 2027-01-01 is `2026-W53`. Deriving the year from the date itself gets
 * exactly those edges wrong, and then a link opens a week the day is not in.
 */
export function isoWeekCode(day: Date): string {
  const thursday = addDays(startOfWeek(day), 3);
  const firstThursday = addDays(startOfWeek(new Date(thursday.getFullYear(), 0, 4)), 3);
  const week =
    1 + Math.round((thursday.getTime() - firstThursday.getTime()) / (DAYS_IN_WEEK * DAY_MS));
  return `${thursday.getFullYear()}-W${String(week).padStart(PAD, '0')}`;
}

/** Every date of the month `day` falls in, first to last. */
export function monthDates(day: Date): Date[] {
  const first = new Date(day.getFullYear(), day.getMonth(), 1);
  const dates: Date[] = [];
  for (let cursor = first; cursor.getMonth() === first.getMonth(); cursor = addDays(cursor, 1)) {
    dates.push(cursor);
  }
  return dates;
}

/**
 * The state of one date, given what the API said about it.
 *
 * A date the API has no row for is `empty` when it is past and `future` when it
 * is not — the timeline has to show the frame ahead as unlived rather than as
 * unrecorded.
 */
export function dayStatus(
  day: DayListItem | undefined,
  date: string,
  today: string
): DayStatus {
  if (day !== undefined) {
    if (day.verdict === 'won') return 'won';
    if (day.verdict === 'lost') return 'lost';
    return 'open';
  }
  return date > today ? 'future' : 'empty';
}

/** Every day of a range by its date, so a square is a lookup rather than a scan. */
export function daysByDate(days: DayListItem[]): Map<string, DayListItem> {
  return new Map(days.map((day) => [day.date, day]));
}

/** The counter `life.html` showed above the grid. */
export interface LifeCounter {
  /** Whole years lived. */
  years: number;
  weeksLived: number;
  /** Weeks in the frame — the frame in years, not a prediction of the end. */
  weeksTotal: number;
  weeksLeft: number;
  /** Share of the frame lived, 0..100. */
  percent: number;
}

/**
 * Weeks lived and weeks left inside a frame of `targetYears`.
 *
 * The same arithmetic `life.html` ran: whole weeks between the birth date and
 * today, against `targetYears × 52.1775` rounded. Kept identical on purpose —
 * the acceptance case is that the number on the new page matches the number the
 * old page showed, and a "better" formula would fail it.
 */
export function lifeCounter(
  birth: string,
  targetYears: number,
  today: Date = new Date()
): LifeCounter {
  const born = fromISODate(birth);
  const noon = new Date(today);
  noon.setHours(0, 0, 0, 0);
  const livedDays = Math.floor((noon.getTime() - born.getTime()) / DAY_MS);
  const weeksLived = Math.floor(livedDays / DAYS_IN_WEEK);
  const weeksTotal = Math.round(targetYears * WEEKS_PER_YEAR);
  const weeksLeft = Math.max(0, weeksTotal - weeksLived);

  let years = noon.getFullYear() - born.getFullYear();
  const anniversary = new Date(born);
  anniversary.setFullYear(born.getFullYear() + years);
  if (anniversary > noon) years -= 1;

  return {
    years,
    weeksLived,
    weeksTotal,
    weeksLeft,
    percent: Math.min(100, (weeksLived / weeksTotal) * 100),
  };
}

/** One month of the sidebar: its days, newest first. */
export interface SidebarMonth {
  /** `2026-08` — stable across renders and unique inside a year. */
  key: string;
  /** Month number, 1-12. */
  month: number;
  days: DayListItem[];
}

/** One year of the sidebar, with the months that have days in them. */
export interface SidebarYear {
  year: number;
  months: SidebarMonth[];
}

/**
 * Days grouped year → month, newest first inside every level.
 *
 * Newest first because the sidebar is opened to reach yesterday far more often
 * than to reach last March, and a list that starts in January makes the common
 * case a scroll.
 */
export function groupByYearAndMonth(days: DayListItem[]): SidebarYear[] {
  const years = new Map<number, Map<number, DayListItem[]>>();
  for (const day of days) {
    const [year, month] = day.date.split('-').map(Number);
    const months = years.get(year) ?? new Map<number, DayListItem[]>();
    months.set(month, [...(months.get(month) ?? []), day]);
    years.set(year, months);
  }
  return [...years.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([year, months]) => ({
      year,
      months: [...months.entries()]
        .sort((a, b) => b[0] - a[0])
        .map(([month, monthDays]) => ({
          key: `${year}-${String(month).padStart(PAD, '0')}`,
          month,
          days: [...monthDays].sort((a, b) => b.date.localeCompare(a.date)),
        })),
    }));
}

/** Key of the month a date belongs to — what the sidebar opens expanded. */
export function monthKeyOf(date: string): string {
  return date.slice(0, 'YYYY-MM'.length);
}

const MONTH_NAMES = [
  'январь',
  'февраль',
  'март',
  'апрель',
  'май',
  'июнь',
  'июль',
  'август',
  'сентябрь',
  'октябрь',
  'ноябрь',
  'декабрь',
];

export const WEEKDAY_SHORT = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];

/** Human name of a month number, 1-12. */
export function monthName(month: number): string {
  return MONTH_NAMES[month - 1] ?? String(month);
}
