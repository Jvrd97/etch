// [review:need-review] PHASE-01/73-dashboard-hero-today-ring
// summary: unit tests for the hero "logged N ago" line — units, boundaries, UTC-less timestamps, clock skew

import { describe, expect, it } from 'bun:test';
import { formatLoggedAgo, formatRelativeTime } from './relative-time';

const NOW = new Date('2026-08-10T12:00:00Z');

describe('formatRelativeTime', () => {
  it('calls the last minute just now', () => {
    expect(formatRelativeTime('2026-08-10T11:59:30Z', NOW)).toBe('just now');
  });

  it('counts whole minutes', () => {
    expect(formatRelativeTime('2026-08-10T11:59:00Z', NOW)).toBe('1 minute ago');
    expect(formatRelativeTime('2026-08-10T11:46:00Z', NOW)).toBe('14 minutes ago');
  });

  it('switches to hours at the hour boundary', () => {
    expect(formatRelativeTime('2026-08-10T11:00:00Z', NOW)).toBe('1 hour ago');
    expect(formatRelativeTime('2026-08-10T07:30:00Z', NOW)).toBe('4 hours ago');
  });

  it('switches to days at the day boundary', () => {
    expect(formatRelativeTime('2026-08-09T12:00:00Z', NOW)).toBe('1 day ago');
    expect(formatRelativeTime('2026-08-04T12:00:00Z', NOW)).toBe('6 days ago');
  });

  it('falls back to an absolute day once the relative count stops being readable', () => {
    expect(formatRelativeTime('2026-03-05T09:15:00Z', NOW)).toBe('on 5 Mar 2026');
  });

  it('reads a timestamp without a timezone designator as UTC', () => {
    expect(formatRelativeTime('2026-08-10T11:46:00', NOW)).toBe('14 minutes ago');
  });

  it('does not report the future when the client clock runs behind', () => {
    expect(formatRelativeTime('2026-08-10T12:05:00Z', NOW)).toBe('just now');
  });

  it('degrades to a vague word on an unparseable timestamp', () => {
    expect(formatRelativeTime('not-a-timestamp', NOW)).toBe('recently');
  });
});

describe('formatLoggedAgo', () => {
  it('names the moment as the moment of writing, not of the event', () => {
    expect(formatLoggedAgo('2026-08-10T11:46:00Z', NOW)).toBe('Logged 14 minutes ago');
  });
});
