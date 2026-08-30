// [review:need-review] PHASE-03/127
// summary: tests for the Today card of an obligation — «день 3 из 7, промахов 0» printed from the server's counts, the three states of today's day, and the Russian plural forms both counts need

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { Challenge } from '@/lib/api';
import { formatMisses, formatProgress, isOnToday, plural } from '@/lib/challenges';

const WATER: Challenge = {
  id: 4,
  title: '7 дней подряд ≥ 2 л воды',
  category_id: 1,
  field_id: 7,
  rule_kind: 'metric_at_least',
  target: '2.000',
  starts_on: '2026-08-29',
  ends_on: '2026-09-04',
  failure_mode: 'any_miss',
  allowed_misses: 0,
  status: 'active',
  failed_on: null,
  total_days: 7,
  day_number: 3,
  done_count: 3,
  misses_used: 0,
  today_verdict: 'pending',
  created_at: '2026-08-29T06:00:00Z',
};

const { default: ChallengeCard } = await import('./ChallengeCard');

afterEach(() => cleanup());

describe('ChallengeCard', () => {
  it('prints the day and the misses the server counted', () => {
    render(<ChallengeCard challenge={{ ...WATER, today_verdict: 'done' }} />);
    expect(screen.getByText(/день 3 из 7, промахов 0/)).toBeTruthy();
  });

  it('says today is still waiting rather than missed', () => {
    render(<ChallengeCard challenge={WATER} />);
    expect(screen.getByText('сегодня ещё не подтверждено')).toBeTruthy();
  });

  it('says today is done once the promise is kept', () => {
    render(<ChallengeCard challenge={{ ...WATER, today_verdict: 'done' }} />);
    expect(screen.getByText('сегодня сделано')).toBeTruthy();
  });
});

describe('challenge labels', () => {
  it('declines both nouns the way Russian does', () => {
    expect(plural(1, 'промах', 'промаха', 'промахов')).toBe('промах');
    expect(plural(2, 'промах', 'промаха', 'промахов')).toBe('промаха');
    expect(plural(5, 'промах', 'промаха', 'промахов')).toBe('промахов');
    expect(plural(11, 'промах', 'промаха', 'промахов')).toBe('промахов');
    expect(plural(21, 'промах', 'промаха', 'промахов')).toBe('промах');
  });

  it('counts misses as a number even when there are none', () => {
    expect(formatMisses(WATER)).toBe('промахов 0');
    expect(formatMisses({ ...WATER, misses_used: 1 })).toBe('промах 1');
  });

  it('says a challenge that has not started yet is not yet on day one', () => {
    expect(formatProgress({ ...WATER, day_number: 0 })).toContain('начнётся');
  });

  it('keeps only running challenges on Today', () => {
    expect(isOnToday(WATER)).toBe(true);
    expect(isOnToday({ ...WATER, status: 'won' })).toBe(false);
    // Window over: the server answers with no verdict for today at all.
    expect(isOnToday({ ...WATER, today_verdict: null })).toBe(false);
  });
});
