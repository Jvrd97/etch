// [review:need-review] PHASE-03/127, PHASE-03/128
// summary: tests for the Today card of an obligation — «день 3 из 7, промахов 0 из 2» printed from the server's counts, the three states of today's day, how the challenge ended, the button that counts a day by hand, and the Russian plural forms both counts need

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { Challenge } from '@/lib/api';
import {
  canCountToday,
  formatMisses,
  formatProgress,
  formatStatus,
  isOnToday,
  plural,
} from '@/lib/challenges';

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
  misses_left: 0,
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

  it('offers to count the day by hand and reports which challenge was tapped', () => {
    const counted = mock(() => {});
    render(<ChallengeCard challenge={WATER} onCountToday={counted} />);
    fireEvent.click(screen.getByText('Засчитать день'));
    expect(counted).toHaveBeenCalledTimes(1);
  });

  it('does not offer to count a day that is already done', () => {
    render(
      <ChallengeCard
        challenge={{ ...WATER, today_verdict: 'done' }}
        onCountToday={() => {}}
      />,
    );
    expect(screen.queryByText('Засчитать день')).toBeNull();
  });

  it('prints the misses against the budget on the card', () => {
    render(
      <ChallengeCard
        challenge={{
          ...WATER,
          failure_mode: 'budget',
          allowed_misses: 2,
          misses_used: 1,
          misses_left: 1,
        }}
      />,
    );
    expect(screen.getByText(/промах 1 из 2/)).toBeTruthy();
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

  it('shows the misses against the budget rather than as a bare number', () => {
    expect(formatMisses(WATER)).toBe('промахов 0 из 0');
    const budgeted: Challenge = {
      ...WATER,
      failure_mode: 'budget',
      allowed_misses: 2,
      misses_used: 1,
      misses_left: 1,
    };
    expect(formatMisses(budgeted)).toBe('промах 1 из 2');
  });

  it('names how the challenge ended and when', () => {
    expect(formatStatus(WATER)).toBe('идёт');
    expect(formatStatus({ ...WATER, status: 'won' })).toBe('выигран');
    expect(
      formatStatus({ ...WATER, status: 'failed', failed_on: '2026-08-31' }),
    ).toBe('завален 2026-08-31');
  });

  it('offers to count a day only where counting changes something', () => {
    expect(canCountToday(WATER)).toBe(true);
    expect(canCountToday({ ...WATER, today_verdict: 'miss' })).toBe(true);
    expect(canCountToday({ ...WATER, today_verdict: 'done' })).toBe(false);
    expect(canCountToday({ ...WATER, status: 'won' })).toBe(false);
  });

  it('says a challenge that has not started yet is not yet on day one', () => {
    expect(formatProgress({ ...WATER, day_number: 0 })).toContain('начнётся');
  });

  it('keeps only the challenges Today can still act on', () => {
    expect(isOnToday(WATER)).toBe(true);
    expect(isOnToday({ ...WATER, status: 'won' })).toBe(false);
    expect(isOnToday({ ...WATER, status: 'abandoned' })).toBe(false);
    // Failed stays: a counted day can bring it back, and that button lives here.
    expect(isOnToday({ ...WATER, status: 'failed' })).toBe(true);
    // Window over: the server answers with no verdict for today at all.
    expect(isOnToday({ ...WATER, today_verdict: null })).toBe(false);
  });
});
