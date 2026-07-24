// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: unit tests for toISODate/todayISO — shape of the produced date string and the injected clock

import { describe, expect, it } from 'bun:test';
import { toISODate, todayISO } from './date';

describe('toISODate', () => {
  it('formats an arbitrary past date as YYYY-MM-DD', () => {
    expect(toISODate(new Date('1999-11-30T08:15:00.000Z'))).toBe('1999-11-30');
  });

  it('zero-pads a single-digit month and day', () => {
    expect(toISODate(new Date('2024-03-07T12:00:00.000Z'))).toBe('2024-03-07');
  });

  it('keeps the leap day of a leap year', () => {
    expect(toISODate(new Date('2024-02-29T23:59:59.999Z'))).toBe('2024-02-29');
  });

  it('never leaks the time part', () => {
    expect(toISODate(new Date('2030-06-01T21:45:12.345Z'))).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe('todayISO', () => {
  it('formats the injected moment as YYYY-MM-DD', () => {
    expect(todayISO(new Date('2026-07-24T18:30:00.000Z'))).toBe('2026-07-24');
  });

  it('keeps zero-padding for single-digit months and days', () => {
    expect(todayISO(new Date('2026-01-05T00:00:00.000Z'))).toBe('2026-01-05');
  });

  it('drops the time part entirely', () => {
    expect(todayISO(new Date('2026-12-31T23:59:59.999Z'))).toBe('2026-12-31');
  });

  it('defaults to the current clock and returns a plain date string', () => {
    expect(todayISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
