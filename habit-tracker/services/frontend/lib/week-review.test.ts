// [review:need-review] PHASE-03/221
// summary: tests for the week review vocabulary — minutes as words, signed deltas, the note under an unfinished week, health values by unit, the empty-week test, and the narrative error picked by HTTP status

import { describe, expect, it } from 'bun:test';
import type { WeekReview, WeekReviewHealth, WeekReviewWindow } from '@/lib/api';
import {
  NARRATIVE_ERROR_FALLBACK,
  NARRATIVE_ERRORS,
  deltaCount,
  deltaMinutes,
  deltaPoints,
  formatHealthDelta,
  formatHealthValue,
  formatMinutes,
  isEmptyWeek,
  narrativeErrorText,
  NO_COUNTED_DAYS_TEXT,
  inShell,
  partialNote,
  periodText,
  retroHref,
  shortDate,
  trendOf,
  weekHref,
} from '@/lib/week-review';
import { weekReviewFixture } from '@/components/week-review/test-fixture';

function windowOf(patch: Partial<WeekReviewWindow>): WeekReviewWindow {
  return { ...weekReviewFixture().window, ...patch };
}

describe('minutes as words', () => {
  it('drops the empty tail and pads the minutes', () => {
    expect(formatMinutes(0)).toBe('0 мин');
    expect(formatMinutes(45)).toBe('45 мин');
    expect(formatMinutes(120)).toBe('2 ч');
    expect(formatMinutes(125)).toBe('2 ч 05 мин');
  });
});

describe('signed changes', () => {
  it('prints the sign, and says nothing changed instead of «+0»', () => {
    expect(deltaCount(2)).toBe('+2');
    expect(deltaCount(-1)).toBe('−1');
    expect(deltaCount(0)).toBe('без изменений');
    expect(deltaMinutes(80)).toBe('+1 ч 20 мин');
    expect(deltaMinutes(-45)).toBe('−45 мин');
    expect(deltaPoints(29)).toBe('+29 п.п.');
  });

  it('keeps «no comparison» apart from «no change»', () => {
    expect(deltaMinutes(null)).toBeNull();
    expect(deltaPoints(null)).toBeNull();
    expect(trendOf(null)).toBe('flat');
    expect(trendOf(0)).toBe('flat');
    expect(trendOf(3)).toBe('up');
    expect(trendOf(-3)).toBe('down');
  });
});

describe('the note under an unfinished week', () => {
  it('is absent for a finished week', () => {
    expect(partialNote(windowOf({ is_complete: true }))).toBeNull();
  });

  it('names both counts for a running week', () => {
    const note = partialNote(windowOf({ is_complete: false, counted_days: 3, compared_days: 3 }));
    expect(note).toContain('не закончилась');
    expect(note).toContain('3 из 7');
    expect(note).toContain('первыми 3 днями прошлой недели');
  });

  it('says nothing is counted yet when only the open day has come', () => {
    expect(partialNote(windowOf({ is_complete: false, counted_days: 0, compared_days: 0 }))).toBe(
      NO_COUNTED_DAYS_TEXT
    );
  });

  it('tells the reader that today joins after it is closed', () => {
    const note = partialNote(windowOf({ is_complete: false, counted_days: 2, compared_days: 2 }));
    expect(note).toContain('сегодняшний день войдёт после закрытия');
  });
});

describe('dates and links', () => {
  it('cuts a date without a Date object, so no timezone can move it', () => {
    expect(shortDate('2026-08-24')).toBe('24.08');
    expect(periodText(windowOf({}))).toBe('24.08 — 30.08');
  });

  it('links to the review of a named week', () => {
    expect(weekHref('2026-W36')).toBe('/week/review/2026-W36');
  });

  it('keeps the reader in the mobile shell when the screen is the compact one', () => {
    expect(weekHref('2026-W36', true)).toBe('/m/week/review/2026-W36');
    expect(retroHref('2026-W36', true)).toBe('/m/week/2026-W36');
    expect(retroHref('2026-W36')).toBe('/week/2026-W36');
    expect(inShell('/week/review', true)).toBe('/m/week/review');
  });
});

describe('health values', () => {
  const steps = (patch: Partial<WeekReviewHealth>): WeekReviewHealth => ({
    ...weekReviewFixture().health[1],
    ...patch,
  });

  it('prints minutes as hours and counts as integers', () => {
    expect(formatHealthValue('min', 430)).toBe('7 ч 10 мин');
    expect(formatHealthValue('count', 7421.4)).toBe((7421).toLocaleString('ru-RU'));
    expect(formatHealthValue('kg', 80.5)).toBe('80.5 kg');
  });

  it('formats the change in the unit of the metric', () => {
    expect(formatHealthDelta(steps({ unit: 'min', delta_avg_per_day: -40 }))).toBe(
      '−40 мин'
    );
    expect(formatHealthDelta(steps({ delta_avg_per_day: null }))).toBeNull();
  });
});

describe('an empty week', () => {
  it('is one with no closed days, tasks, minutes, categories or health', () => {
    const empty: WeekReview = {
      ...weekReviewFixture(),
      totals: { ...weekReviewFixture().totals, closed_days: 0, tasks_total: 0, role_minutes: 0 },
      categories: [],
      habit_streaks: [],
      health: weekReviewFixture().health.map((m) => ({ ...m, days_with_data: 0 })),
    };
    expect(isEmptyWeek(empty)).toBe(true);
    expect(isEmptyWeek(weekReviewFixture())).toBe(false);
  });

  it('is not empty while an avoid habit has a streak to show', () => {
    const base = weekReviewFixture();
    const streakOnly: WeekReview = {
      ...base,
      totals: { ...base.totals, closed_days: 0, tasks_total: 0, role_minutes: 0 },
      categories: [],
      health: base.health.map((m) => ({ ...m, days_with_data: 0 })),
    };
    expect(isEmptyWeek(streakOnly)).toBe(false);
    expect(isEmptyWeek({ ...streakOnly, habit_streaks: [] })).toBe(true);
  });

  it('is not empty when only health has a day', () => {
    const base = weekReviewFixture();
    const healthOnly: WeekReview = {
      ...base,
      totals: { ...base.totals, closed_days: 0, tasks_total: 0, role_minutes: 0 },
      categories: [],
      habit_streaks: [],
    };
    expect(isEmptyWeek(healthOnly)).toBe(false);
  });
});

describe('narrative errors', () => {
  it('reads the status off the error by shape', () => {
    for (const status of [422, 502, 503]) {
      expect(narrativeErrorText({ status })).toBe(NARRATIVE_ERRORS[status]);
    }
  });

  it('falls back for anything else', () => {
    expect(narrativeErrorText({ status: 500 })).toBe(NARRATIVE_ERROR_FALLBACK);
    expect(narrativeErrorText(new Error('x'))).toBe(NARRATIVE_ERROR_FALLBACK);
    expect(narrativeErrorText(null)).toBe(NARRATIVE_ERROR_FALLBACK);
  });
});
