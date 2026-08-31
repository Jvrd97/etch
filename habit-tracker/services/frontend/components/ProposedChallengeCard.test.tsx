// [review:need-review] PHASE-03/129
// summary: component tests for a proposal on Today — the rule reads as a sentence and never as JSON, no count of a challenge that is not counting yet, the two buttons report the proposal they belong to, and «принять» says out loud that the past days of the window count too

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { Category, Challenge } from '@/lib/api';
import { describeRule, isOnToday, isProposal } from '@/lib/challenges';

const WATER: Category = {
  id: 1,
  name: 'Вода',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  fields: [
    {
      id: 7,
      category_id: 1,
      name: 'Объём',
      field_type: 'number',
      is_required: false,
      order: 0,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:00:00Z',
    },
  ],
};

function proposal(overrides: Partial<Challenge> = {}): Challenge {
  return {
    id: 9,
    title: 'месяц без обезболивающих',
    category_id: 1,
    field_id: 7,
    rule_kind: 'metric_at_least',
    target: '2000',
    starts_on: '2026-09-01',
    ends_on: '2026-09-14',
    failure_mode: 'budget',
    allowed_misses: 2,
    status: 'proposed',
    origin: 'ai',
    failed_on: null,
    total_days: 14,
    day_number: 0,
    done_count: 0,
    misses_used: 0,
    misses_left: 2,
    today_verdict: null,
    created_at: '2026-08-31T06:00:00Z',
    ...overrides,
  };
}

const { default: ProposedChallengeCard, ACCEPT_HINT, ACCEPT_LABEL, DECLINE_LABEL } =
  await import('./ProposedChallengeCard');

afterEach(() => {
  cleanup();
});

describe('ProposedChallengeCard', () => {
  it('spells the rule as a sentence a person reads, not as JSON', () => {
    render(
      <ProposedChallengeCard
        challenge={proposal()}
        categories={[WATER]}
        onAccept={() => {}}
        onDecline={() => {}}
      />
    );

    expect(screen.getByText('Вода: Объём ≥ 2000, 14 дней, допускается 2 промаха'))
      .toBeDefined();
    // Ни одного признака сырого ответа модели на экране.
    expect(screen.queryByText(/metric_at_least/)).toBeNull();
    expect(screen.queryByText(/\{/)).toBeNull();
  });

  it('shows the window in dates and who proposed it', () => {
    render(
      <ProposedChallengeCard
        challenge={proposal()}
        categories={[WATER]}
        onAccept={() => {}}
        onDecline={() => {}}
      />
    );

    expect(screen.getByText(/с 2026-09-01 по 2026-09-14/)).toBeDefined();
    expect(screen.getByText(/предложил разбор дня/)).toBeDefined();
  });

  it('prints no count of a challenge that is not counting yet', () => {
    render(
      <ProposedChallengeCard
        challenge={proposal()}
        categories={[WATER]}
        onAccept={() => {}}
        onDecline={() => {}}
      />
    );

    expect(screen.queryByText(/день 0 из 14/)).toBeNull();
    expect(screen.queryByText(/промахов 0/)).toBeNull();
  });

  it('says that accepting counts the days already lived', () => {
    render(
      <ProposedChallengeCard
        challenge={proposal()}
        categories={[WATER]}
        onAccept={() => {}}
        onDecline={() => {}}
      />
    );

    expect(screen.getByText(ACCEPT_HINT)).toBeDefined();
  });

  it('reports the proposal each button belongs to', () => {
    const accepted = mock((challenge: Challenge) => challenge.id);
    const declined = mock((challenge: Challenge) => challenge.id);
    render(
      <ProposedChallengeCard
        challenge={proposal({ id: 42 })}
        categories={[WATER]}
        onAccept={accepted}
        onDecline={declined}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: ACCEPT_LABEL }));
    fireEvent.click(screen.getByRole('button', { name: DECLINE_LABEL }));

    expect(accepted.mock.calls[0][0].id).toBe(42);
    expect(declined.mock.calls[0][0].id).toBe(42);
  });

  it('locks both buttons while the answer is in flight', () => {
    render(
      <ProposedChallengeCard
        challenge={proposal()}
        categories={[WATER]}
        onAccept={() => {}}
        onDecline={() => {}}
        answering
      />
    );

    expect((screen.getByRole('button', { name: ACCEPT_LABEL }) as HTMLButtonElement).disabled).toBe(
      true
    );
    expect(
      (screen.getByRole('button', { name: DECLINE_LABEL }) as HTMLButtonElement).disabled
    ).toBe(true);
  });
});

describe('a proposal among the obligations', () => {
  it('does not join the challenges that are running today', () => {
    expect(isProposal(proposal())).toBe(true);
    expect(isOnToday(proposal())).toBe(false);
  });

  it('still counts as running once it has been accepted', () => {
    const accepted = proposal({ status: 'active', today_verdict: 'pending' });
    expect(isProposal(accepted)).toBe(false);
    expect(isOnToday(accepted)).toBe(true);
  });

  it('names a rule without a threshold without inventing one', () => {
    const abstain = proposal({
      rule_kind: 'abstain',
      target: null,
      failure_mode: 'any_miss',
      allowed_misses: 0,
      total_days: 30,
    });
    expect(describeRule(abstain, [WATER])).toBe('Вода: Объём без срыва, 30 дней');
  });
});
