// [review:need-review] PHASE-03/94
// summary: unit tests for the timeline helpers — the three states of a day square (an unclosed day is not a lost one), the weeks-left counter matching what life.html computed, ISO week codes at the year edges, and the year → month grouping the sidebar draws

import { describe, expect, it } from 'bun:test';
import type { DayListItem } from '@/lib/api';
import {
  DEFAULT_BIRTH,
  DEFAULT_TARGET_YEARS,
  dayStatus,
  groupByYearAndMonth,
  isoWeekCode,
  lifeCounter,
  monthKeyOf,
  fromISODate,
  startOfWeek,
  toISODate,
} from '@/lib/life';

function day(date: string, overrides: Partial<DayListItem> = {}): DayListItem {
  return {
    date,
    title: '',
    verdict: null,
    verdict_origin: 'none',
    done: 0,
    total: 0,
    ...overrides,
  };
}

const TODAY = '2026-08-30';

describe('dayStatus', () => {
  it('tells a day nobody closed from a day that was lost', () => {
    // The acceptance case: three states, not two. `life.py` painted from a
    // regexp over prose and could only produce the first two.
    expect(dayStatus(day('2026-08-28', { verdict: 'won' }), '2026-08-28', TODAY)).toBe('won');
    expect(dayStatus(day('2026-08-29', { verdict: 'lost' }), '2026-08-29', TODAY)).toBe('lost');
    expect(dayStatus(day('2026-08-30'), '2026-08-30', TODAY)).toBe('open');
  });

  it('separates a past date with no record from one still ahead', () => {
    expect(dayStatus(undefined, '2026-08-01', TODAY)).toBe('empty');
    expect(dayStatus(undefined, '2026-09-01', TODAY)).toBe('future');
  });
});

describe('lifeCounter', () => {
  it('computes weeks lived and weeks left the way life.html did', () => {
    // The frame of 97 years is 5061 weeks (97 × 52.1775, rounded), and a person
    // born on 2000-05-11 has lived 1372 whole weeks by 2026-08-30. The numbers
    // are spelled out because the acceptance case is "the same as the old page",
    // and a formula rewritten "better" would quietly fail it.
    const counter = lifeCounter(DEFAULT_BIRTH, DEFAULT_TARGET_YEARS, fromISODate(TODAY));

    expect(counter.weeksTotal).toBe(5061);
    expect(counter.weeksLived).toBe(1372);
    expect(counter.weeksLeft).toBe(5061 - 1372);
    expect(counter.years).toBe(26);
  });

  it('never reports a negative number of weeks left', () => {
    const counter = lifeCounter('1900-01-01', 50, fromISODate(TODAY));

    expect(counter.weeksLeft).toBe(0);
    expect(counter.percent).toBe(100);
  });
});

describe('isoWeekCode', () => {
  it('names the week the ticket was written in', () => {
    expect(isoWeekCode(fromISODate('2026-08-24'))).toBe('2026-W35');
    expect(isoWeekCode(fromISODate('2026-08-30'))).toBe('2026-W35');
  });

  it('puts a january date in last year’s week when the Thursday says so', () => {
    // 2027-01-01 is a Friday; its Thursday is 2026-12-31, so the week is
    // 2026-W53. Deriving the year from the date itself gets this wrong.
    expect(isoWeekCode(fromISODate('2027-01-01'))).toBe('2026-W53');
    expect(isoWeekCode(fromISODate('2026-01-01'))).toBe('2026-W01');
  });
});

describe('startOfWeek', () => {
  it('returns the Monday, including on a Sunday', () => {
    expect(toISODate(startOfWeek(fromISODate('2026-08-30')))).toBe('2026-08-24');
    expect(toISODate(startOfWeek(fromISODate('2026-08-24')))).toBe('2026-08-24');
  });
});

describe('groupByYearAndMonth', () => {
  const grouped = groupByYearAndMonth([
    day('2026-07-31'),
    day('2026-08-01'),
    day('2026-08-30'),
    day('2025-12-31'),
  ]);

  it('groups year then month, newest first at both levels', () => {
    expect(grouped.map((year) => year.year)).toEqual([2026, 2025]);
    expect(grouped[0].months.map((month) => month.month)).toEqual([8, 7]);
  });

  it('keeps the days of a month newest first', () => {
    expect(grouped[0].months[0].days.map((one) => one.date)).toEqual([
      '2026-08-30',
      '2026-08-01',
    ]);
  });

  it('keys a month so the sidebar can open the one the reader is in', () => {
    expect(grouped[0].months[0].key).toBe(monthKeyOf('2026-08-30'));
  });
});
