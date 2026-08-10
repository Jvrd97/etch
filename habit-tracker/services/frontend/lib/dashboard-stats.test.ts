// [review:need-review] PHASE-01/73-dashboard-hero-today-ring
// summary: unit tests for computeDashboardStats (real total + recent feed) and for computeDashboardHero — today's ring, the last written entry and the tip

import { describe, expect, it } from 'bun:test';
import type { Category, Entry, Field } from './api';
import {
  computeDashboardHero,
  computeDashboardStats,
  RECENT_ENTRIES_LIMIT,
} from './dashboard-stats';

function makeEntry(id: number, entryDate: string): Entry {
  return {
    id,
    category_id: 1,
    entry_date: entryDate,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    values: [],
  };
}

/**
 * Noon on 2026-08-10 *in the machine's own timezone*.
 *
 * `computeDashboardHero` dates the moment through `todayISO`, i.e. the local
 * calendar, so pinning the instant in UTC would make `TODAY` wrong wherever the
 * offset pushes noon-UTC onto another day (UTC+12/+13 read it as the 11th) and
 * the journal-staleness assertions below would count a day too few.
 */
const NOW = new Date(2026, 7, 10, 12, 0, 0);
const TODAY = '2026-08-10';

/** An ISO timestamp `minutes` before {@link NOW}, in the same local frame. */
function minutesBeforeNow(minutes: number): string {
  return new Date(NOW.getTime() - minutes * 60 * 1000).toISOString();
}

function makeField(id: number, categoryId: number, name: string): Field {
  return {
    id,
    category_id: categoryId,
    name,
    field_type: 'number',
    is_required: false,
    order: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

function makeCategory(id: number, name: string): Category {
  return {
    id,
    name,
    display_mode: 'form',
    streak_mode: 'build',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    fields: [makeField(id * 10, id, `${name} count`)],
  };
}

const PUSHUPS = makeCategory(1, 'Pushups');
const WATER = makeCategory(2, 'Water');

/** An entry for `category`, dated today, written at `createdAt`. */
function loggedEntry(id: number, category: Category, amount: string, createdAt: string): Entry {
  const field = category.fields[0];
  return {
    id,
    category_id: category.id,
    entry_date: TODAY,
    created_at: createdAt,
    updated_at: createdAt,
    values: [{ id, entry_id: id, field_id: field.id, value: amount }],
  };
}

const PUSHUPS_ENTRY = loggedEntry(31, PUSHUPS, '30', minutesBeforeNow(14));
const WATER_ENTRY = loggedEntry(32, WATER, '6', minutesBeforeNow(10));

const SETTLED_HERO = {
  categories: [PUSHUPS, WATER],
  todayEntries: [PUSHUPS_ENTRY, WATER_ENTRY],
  loggedYesterday: true,
  lastEntry: WATER_ENTRY,
  lastJournalDate: TODAY,
  now: NOW,
};

describe('computeDashboardStats', () => {
  it('counts the real entries total, not a limited slice (parity with iOS)', () => {
    const entries = Array.from({ length: 12 }, (_, i) => makeEntry(i + 1, '2026-07-20'));

    const stats = computeDashboardStats(3, entries, 7);

    expect(stats.categoriesCount).toBe(3);
    expect(stats.entriesCount).toBe(12);
    expect(stats.journalCount).toBe(7);
  });

  it('caps the recent feed at RECENT_ENTRIES_LIMIT, newest first (date desc, id desc on ties)', () => {
    const entries = [
      makeEntry(3, '2026-07-18'),
      makeEntry(6, '2026-07-21'),
      makeEntry(1, '2026-07-20'),
      makeEntry(2, '2026-07-20'),
      makeEntry(4, '2026-07-19'),
      makeEntry(5, '2026-07-17'),
    ];

    const stats = computeDashboardStats(0, entries, 0);

    expect(stats.recentEntries.map((e) => e.id)).toEqual([6, 2, 1, 4, 3]);
    expect(stats.recentEntries.length).toBe(RECENT_ENTRIES_LIMIT);
  });

  it('does not mutate the input entries array', () => {
    const entries = [makeEntry(1, '2026-07-18'), makeEntry(2, '2026-07-20')];
    const snapshot = entries.map((e) => e.id);

    computeDashboardStats(0, entries, 0);

    expect(entries.map((e) => e.id)).toEqual(snapshot);
  });

  it('handles an empty entries list', () => {
    const stats = computeDashboardStats(0, [], 0);
    expect(stats.entriesCount).toBe(0);
    expect(stats.recentEntries).toEqual([]);
  });
});

describe('computeDashboardHero', () => {
  it("counts today's entries, not the whole history", () => {
    const hero = computeDashboardHero(SETTLED_HERO);

    expect(hero.entriesToday).toBe(2);
  });

  it('fills the ring by how much of today is covered, so it can go back down', () => {
    const full = computeDashboardHero(SETTLED_HERO);
    const half = computeDashboardHero({ ...SETTLED_HERO, todayEntries: [PUSHUPS_ENTRY] });
    const empty = computeDashboardHero({
      ...SETTLED_HERO,
      todayEntries: [],
      lastEntry: null,
    });

    expect(full.ringProgress).toBe(1);
    expect(half.ringProgress).toBe(0.5);
    expect(empty.ringProgress).toBe(0);
  });

  it('never overfills the ring when a category is logged twice in a day', () => {
    const hero = computeDashboardHero({
      ...SETTLED_HERO,
      todayEntries: [
        PUSHUPS_ENTRY,
        WATER_ENTRY,
        loggedEntry(33, WATER, '2', minutesBeforeNow(5)),
      ],
    });

    expect(hero.ringProgress).toBe(1);
    expect(hero.entriesToday).toBe(3);
  });

  it('reports the last written entry with its category, value and time of writing', () => {
    const hero = computeDashboardHero({ ...SETTLED_HERO, lastEntry: PUSHUPS_ENTRY });

    expect(hero.lastEntry).toEqual({
      entryId: PUSHUPS_ENTRY.id,
      categoryName: 'Pushups',
      value: '30',
      loggedAgo: 'Logged 14 minutes ago',
    });
  });

  it('has no last entry when nothing was ever written', () => {
    const hero = computeDashboardHero({ ...SETTLED_HERO, lastEntry: null, todayEntries: [] });

    expect(hero.lastEntry).toBeNull();
  });

  it('shows no value for a checklist entry, which carries a tick and not a number', () => {
    const sleep: Category = {
      id: 3,
      name: 'Sleep',
      display_mode: 'checklist',
      streak_mode: 'build',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      fields: [{ ...makeField(30, 3, 'Slept 8h'), field_type: 'boolean' }],
    };
    const ticked: Entry = {
      id: 41,
      category_id: sleep.id,
      entry_date: TODAY,
      created_at: minutesBeforeNow(3),
      updated_at: minutesBeforeNow(3),
      values: [{ id: 41, entry_id: 41, field_id: 30, value: 'true' }],
    };

    const hero = computeDashboardHero({
      ...SETTLED_HERO,
      categories: [sleep],
      todayEntries: [ticked],
      lastEntry: ticked,
    });

    expect(hero.lastEntry?.categoryName).toBe('Sleep');
    expect(hero.lastEntry?.value).toBeNull();
  });

  it('still names an entry whose category no longer exists, without guessing a value', () => {
    const hero = computeDashboardHero({ ...SETTLED_HERO, categories: [] });

    expect(hero.lastEntry?.categoryName.length).toBeGreaterThan(0);
    // Without the category there is no field to say which stored value is the
    // number, so the line stays a name rather than showing an arbitrary one.
    expect(hero.lastEntry?.value).toBeNull();
  });

  it('confirms a day where everything tracked is logged', () => {
    expect(computeDashboardHero(SETTLED_HERO).tip.kind).toBe('all-logged');
  });

  it('asks for a first entry on an untouched day', () => {
    const hero = computeDashboardHero({
      ...SETTLED_HERO,
      todayEntries: [],
      lastEntry: null,
      // Nothing yesterday either, so the tip cannot be about a run at risk
      // whatever the machine's timezone makes of the hour.
      loggedYesterday: false,
    });

    expect(hero.tip.kind).toBe('nothing-logged');
  });

  it('measures journal staleness against today, not against the epoch', () => {
    const hero = computeDashboardHero({ ...SETTLED_HERO, lastJournalDate: '2026-08-05' });

    expect(hero.tip.kind).toBe('journal-stale');
    expect(hero.tip.text).toContain('5 days');
  });

  it('reads a missing journal as never written', () => {
    const hero = computeDashboardHero({ ...SETTLED_HERO, lastJournalDate: null });

    expect(hero.tip.kind).toBe('journal-stale');
  });
});
