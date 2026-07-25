// [review:need-review] PHASE-01/56-local-calendar-date-instead-of-utc
// summary: unit tests for toISODate/todayISO — local-calendar date under a non-zero TZ offset

import { afterAll, beforeAll, describe, expect, it } from 'bun:test';
import { toISODate, todayISO } from './date';

// The whole point of this slice is that the produced date follows the user's
// local calendar, so the suite pins an explicit east-of-Greenwich zone
// (UTC+3) and asserts against local, not UTC, day boundaries.
const originalTZ = process.env.TZ;
beforeAll(() => {
  process.env.TZ = 'Europe/Moscow';
});
afterAll(() => {
  process.env.TZ = originalTZ;
});

describe('toISODate', () => {
  it('maps the early local hours to today, not to the UTC-yesterday', () => {
    // 2026-07-24T00:30 local (UTC+3) is 2026-07-23T21:30Z; the UTC calendar
    // would call this yesterday, the local calendar keeps it as the 24th.
    expect(toISODate(new Date('2026-07-24T00:30:00+03:00'))).toBe('2026-07-24');
  });

  it('keeps the last local minute of the day on that day', () => {
    expect(toISODate(new Date('2026-07-24T23:59:00+03:00'))).toBe('2026-07-24');
  });

  it('zero-pads a single-digit month and day', () => {
    expect(toISODate(new Date('2024-03-07T12:00:00+03:00'))).toBe('2024-03-07');
  });

  it('keeps the leap day of a leap year', () => {
    expect(toISODate(new Date('2024-02-29T23:30:00+03:00'))).toBe('2024-02-29');
  });

  it('never leaks the time part', () => {
    expect(toISODate(new Date('2030-06-01T21:45:12.345+03:00'))).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe('todayISO', () => {
  it('places a just-after-midnight local entry on the current local day', () => {
    expect(todayISO(new Date('2026-07-24T00:30:00+03:00'))).toBe('2026-07-24');
  });

  it('keeps zero-padding for single-digit months and days', () => {
    expect(todayISO(new Date('2026-01-05T12:00:00+03:00'))).toBe('2026-01-05');
  });

  it('defaults to the current clock and returns a plain date string', () => {
    expect(todayISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
