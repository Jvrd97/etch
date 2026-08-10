// [review:need-review] PHASE-01/73-dashboard-hero-today-ring
// summary: pure dashboard aggregation — the recent-activity feed (unchanged) plus computeDashboardHero: today's ring, the last written entry and the tip of the day

import type { Category, Entry } from './api';
import { pickDailyTip, type DailyTip, type TrackedCategory } from './daily-tip';
import { todayISO } from './date';
import { formatLoggedAgo } from './relative-time';
import { firstNumberField, partitionTodayCategories } from './today-categories';

/** How many entries the recent-activity feed surfaces (parity with the iOS dashboard). */
export const RECENT_ENTRIES_LIMIT = 5;

export interface DashboardStats {
  categoriesCount: number;
  entriesCount: number;
  journalCount: number;
  recentEntries: Entry[];
}

/**
 * Pure aggregation of the fetched dashboard data.
 *
 * `entriesCount` is the real length of the entries list (not a limit-capped
 * slice), matching the iOS dashboard. The recent-activity feed is newest first
 * (entry_date desc, id desc on ties) and capped at {@link RECENT_ENTRIES_LIMIT};
 * the explicit sort makes the feed order identical to iOS regardless of the
 * backend tie order.
 */
export function computeDashboardStats(
  categoriesCount: number,
  entries: Entry[],
  journalTotal: number,
): DashboardStats {
  const recentEntries = [...entries]
    .sort((a, b) => {
      if (a.entry_date !== b.entry_date) {
        return a.entry_date < b.entry_date ? 1 : -1;
      }
      return b.id - a.id;
    })
    .slice(0, RECENT_ENTRIES_LIMIT);

  return {
    categoriesCount,
    entriesCount: entries.length,
    journalCount: journalTotal,
    recentEntries,
  };
}

/** Shown in place of a category name when the entry's category is gone. */
export const UNKNOWN_CATEGORY_LABEL = 'Entry';

/** Milliseconds in a day — used only to turn a date difference into whole days. */
const MS_PER_DAY = 24 * 60 * 60 * 1000;

/** The last entry the user wrote, as the hero line renders it. */
export interface HeroLastEntry {
  entryId: number;
  categoryName: string;
  /**
   * The number the entry carries, as stored. A bare string: units arrive with
   * #75, and the hero has to read correctly both before and after they do.
   * `null` when the entry stores nothing showable.
   */
  value: string | null;
  /** "Logged 14 minutes ago" — the moment of writing, never of the event. */
  loggedAgo: string;
}

/** Everything the hero card renders, derived and nothing else. */
export interface DashboardHero {
  entriesToday: number;
  /** How much of today is covered, 0..1. */
  ringProgress: number;
  lastEntry: HeroLastEntry | null;
  tip: DailyTip;
}

export interface DashboardHeroInput {
  categories: Category[];
  /** Entries dated today — the day's slice, not the history. */
  todayEntries: Entry[];
  /** Whether yesterday holds any entry; what a run would break from. */
  loggedYesterday: boolean;
  /** The most recently written entry, whatever day it is dated. */
  lastEntry: Entry | null;
  /** `YYYY-MM-DD` of the newest journal note, or `null` when there is none. */
  lastJournalDate: string | null;
  now: Date;
}

/** Whole days between two `YYYY-MM-DD` strings, or `null` if either is unreadable. */
function daysBetweenDates(fromISO: string, toISO: string): number | null {
  const from = Date.parse(`${fromISO}T00:00:00Z`);
  const to = Date.parse(`${toISO}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to)) return null;
  return Math.round((to - from) / MS_PER_DAY);
}

/**
 * Categories the day is measured against: everything on the Today screen except
 * the avoid ones. An avoid category is kept empty on purpose, so counting it as
 * "not logged yet" would ask the user to break the very habit they are avoiding.
 */
function trackedTodayCategories(categories: Category[]): TrackedCategory[] {
  const { checklist, quickForm } = partitionTodayCategories(categories);
  return [...checklist, ...quickForm.map((item) => item.category)].map((category) => ({
    id: category.id,
    name: category.name,
  }));
}

/**
 * The number the hero shows next to the category name, or `null` when there is
 * none to show.
 *
 * Only the category's first number field counts. Falling back to whatever the
 * entry stores first reads a checklist tick as a quantity — "Last entry: Sleep
 * true" — and an unknown category gives no way to tell which of the stored
 * values was the measurement, so both cases render the name alone.
 */
function heroValue(category: Category | undefined, entry: Entry): string | null {
  const numberField = category === undefined ? undefined : firstNumberField(category);
  if (numberField === undefined) return null;
  return entry.values.find((value) => value.field_id === numberField.id)?.value ?? null;
}

/**
 * The hero card of the dashboard: today's ring, the last thing written, the tip.
 *
 * The ring is filled by *coverage of today* — how many of the categories the
 * user tracks already have an entry — and not by a running count against a
 * fixed target. A count-based ring is full forever once the history is long
 * enough, which is exactly the lie this card replaces: it has to be able to
 * empty again at midnight, or it says nothing about the day at all.
 *
 * With nothing tracked for today there is nothing to cover, so the ring falls
 * back to the binary question it can still answer honestly: was anything
 * written today.
 */
export function computeDashboardHero(input: DashboardHeroInput): DashboardHero {
  const { categories, todayEntries, loggedYesterday, lastEntry, lastJournalDate, now } = input;

  const tracked = trackedTodayCategories(categories);
  const loggedCategoryIds = [...new Set(todayEntries.map((entry) => entry.category_id))];
  const coveredCount = tracked.filter((category) =>
    loggedCategoryIds.includes(category.id)
  ).length;

  const ringProgress =
    tracked.length > 0
      ? coveredCount / tracked.length
      : Number(todayEntries.length > 0);

  const daysSinceJournal =
    lastJournalDate === null ? null : daysBetweenDates(lastJournalDate, todayISO(now));

  const lastEntryCategory =
    lastEntry === null
      ? undefined
      : categories.find((category) => category.id === lastEntry.category_id);

  return {
    entriesToday: todayEntries.length,
    ringProgress,
    lastEntry:
      lastEntry === null
        ? null
        : {
            entryId: lastEntry.id,
            categoryName: lastEntryCategory?.name ?? UNKNOWN_CATEGORY_LABEL,
            value: heroValue(lastEntryCategory, lastEntry),
            loggedAgo: formatLoggedAgo(lastEntry.created_at, now),
          },
    tip: pickDailyTip({
      trackedToday: tracked,
      loggedCategoryIds,
      loggedYesterday,
      hour: now.getHours(),
      daysSinceJournal,
    }),
  };
}
