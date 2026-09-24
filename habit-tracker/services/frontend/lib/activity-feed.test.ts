// [review:need-review] #76
// summary: activity-feed tests pin newest-first merging, grouping by the day a record belongs to, and the dashboard's day-or-time label

import { describe, expect, it } from 'bun:test';
import type { Entry, JournalEntry } from './api';
import {
  activityWhen,
  groupActivityFeed,
  mergeActivityFeed,
} from './activity-feed';

const entry = (id: number, entryDate: string, createdAt: string): Entry => ({
  id,
  category_id: 1,
  entry_date: entryDate,
  created_at: createdAt,
  updated_at: createdAt,
  values: [],
});

const journal = (id: number, entryDate: string, createdAt: string): JournalEntry => ({
  id,
  title: 'Day reflection',
  content: 'A note about today',
  entry_date: entryDate,
  created_at: createdAt,
  updated_at: createdAt,
});

// Local noon, so "today" is the 24th in every timezone the suite runs in.
const NOW = new Date(2026, 8, 24, 12);

describe('activity feed', () => {
  it('merges entries and journal notes by created_at, newest first', () => {
    const items = mergeActivityFeed(
      [
        entry(1, '2026-09-24', '2026-09-24T09:00:00Z'),
        entry(2, '2026-09-23', '2026-09-23T10:00:00Z'),
      ],
      [journal(7, '2026-09-24', '2026-09-24T11:00:00Z')]
    );

    expect(items.map(({ kind, createdAt }) => [kind, createdAt])).toEqual([
      ['journal', '2026-09-24T11:00:00Z'],
      ['entry', '2026-09-24T09:00:00Z'],
      ['entry', '2026-09-23T10:00:00Z'],
    ]);
  });

  it('groups by the day a record belongs to, newest day first, as Today, Yesterday, then a date', () => {
    const items = mergeActivityFeed(
      [
        entry(1, '2026-09-24', '2026-09-24T08:00:00Z'),
        entry(2, '2026-09-22', '2026-09-22T08:00:00Z'),
      ],
      [journal(7, '2026-09-23', '2026-09-23T08:00:00Z')]
    );

    expect(groupActivityFeed(items, NOW).map(({ label }) => label)).toEqual([
      'Today',
      'Yesterday',
      'Sep 22, 2026',
    ]);
  });

  it('files a record written today for an earlier day under that earlier day', () => {
    // Backfilled this morning for the 20th: the history belongs to the 20th,
    // even though it is the newest thing written.
    const items = mergeActivityFeed(
      [
        entry(1, '2026-09-20', '2026-09-24T08:00:00Z'),
        entry(2, '2026-09-24', '2026-09-24T07:00:00Z'),
        entry(3, '2026-09-21', '2026-09-21T07:00:00Z'),
      ],
      []
    );

    expect(
      groupActivityFeed(items, NOW).map(({ date, items: dayItems }) => [
        date,
        dayItems.map(({ key }) => key),
      ])
    ).toEqual([
      ['2026-09-24', ['entry-2']],
      ['2026-09-21', ['entry-3']],
      ['2026-09-20', ['entry-1']],
    ]);
  });

  it('labels a record of today by its time and a record of another day by that day', () => {
    const [today, earlier, yesterday] = mergeActivityFeed(
      [
        entry(1, '2026-09-24', '2026-09-24T09:15:00Z'),
        entry(2, '2026-09-19', '2026-09-24T08:00:00Z'),
      ],
      [journal(3, '2026-09-23', '2026-09-24T07:00:00Z')]
    );

    expect(activityWhen(today, NOW).dateTime).toBe('2026-09-24T09:15:00Z');
    expect(activityWhen(earlier, NOW)).toEqual({ dateTime: '2026-09-19', label: 'Sep 19, 2026' });
    expect(activityWhen(yesterday, NOW)).toEqual({ dateTime: '2026-09-23', label: 'Yesterday' });
  });
});
