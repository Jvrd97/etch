// [review:need-review] #76
// summary: merges tracker entries and journal notes into a newest-first activity stream, groups it by the day each record belongs to, and labels a row by its time or its day

import type { Entry, JournalEntry } from './api';
import { previousDay } from './chart-utils';
import { fromISODate, todayISO } from './date';

/**
 * One row of the feed. `entryDate` is the `YYYY-MM-DD` day the record is
 * about; `createdAt` is the moment it was written. The two differ whenever a
 * day is backfilled, and each answers a different question: the history is
 * filed by the first, "what did I write last" is ordered by the second.
 */
export type ActivityFeedItem =
  | { kind: 'entry'; key: string; entryDate: string; createdAt: string; entry: Entry }
  | { kind: 'journal'; key: string; entryDate: string; createdAt: string; journal: JournalEntry };

export interface ActivityFeedGroup {
  /** The `YYYY-MM-DD` day every item of the group belongs to. */
  date: string;
  label: string;
  items: ActivityFeedItem[];
}

/** Merge the independently loaded sources and sort by the moment they were saved. */
export function mergeActivityFeed(
  entries: Entry[],
  journals: JournalEntry[]
): ActivityFeedItem[] {
  return [
    ...entries.map((entry): ActivityFeedItem => ({
      kind: 'entry',
      key: `entry-${entry.id}`,
      entryDate: entry.entry_date,
      createdAt: entry.created_at,
      entry,
    })),
    ...journals.map((journal): ActivityFeedItem => ({
      kind: 'journal',
      key: `journal-${journal.id}`,
      entryDate: journal.entry_date,
      createdAt: journal.created_at,
      journal,
    })),
  ].sort((left, right) => {
    const timeDifference = Date.parse(right.createdAt) - Date.parse(left.createdAt);
    if (timeDifference !== 0) return timeDifference;
    return left.key.localeCompare(right.key);
  });
}

/** "Today", "Yesterday", or a readable date for a `YYYY-MM-DD` day. */
function dayLabel(date: string, now: Date): string {
  const today = todayISO(now);
  if (date === today) return 'Today';
  if (date === previousDay(today)) return 'Yesterday';
  return fromISODate(date).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/** Clock time of the moment a record was written, e.g. "9:15 AM". */
export function activityTime(createdAt: string): string {
  return new Date(createdAt).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
}

/**
 * What an ungrouped row shows in its time slot, plus the matching `dateTime`.
 *
 * A record of today reads best as the time it was written. A record of any
 * other day shows that day instead: "9:15 AM" on a note from last week reads
 * as this morning.
 */
export function activityWhen(
  item: ActivityFeedItem,
  now = new Date()
): { dateTime: string; label: string } {
  return item.entryDate === todayISO(now)
    ? { dateTime: item.createdAt, label: activityTime(item.createdAt) }
    : { dateTime: item.entryDate, label: dayLabel(item.entryDate, now) };
}

/**
 * Group the stream by the day each record belongs to, newest day first.
 * Inside a day the items keep the order they came in.
 */
export function groupActivityFeed(
  items: ActivityFeedItem[],
  now = new Date()
): ActivityFeedGroup[] {
  const groups = new Map<string, ActivityFeedItem[]>();
  for (const item of items) {
    const dayItems = groups.get(item.entryDate);
    if (dayItems === undefined) groups.set(item.entryDate, [item]);
    else dayItems.push(item);
  }

  return [...groups.entries()]
    .sort(([left], [right]) => right.localeCompare(left))
    .map(([date, dayItems]) => ({ date, label: dayLabel(date, now), items: dayItems }));
}
