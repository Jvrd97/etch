// [review:need-review] PHASE-03/179
// summary: component tests of the breathing ceiling on screen — the proposal card is absent when there is nothing to propose, carries its reason and the price of accepting it, disappears on either answer, the day's profile line appears only when a raise is on, and a debt older than a week is drawn as a failed rule beside a week that a debt keeps from being won

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { OvertimeDebt, ProfileInForce, ProfileProposal as Offer, Week } from '@/lib/api';
import {
  ACCEPT_LABEL,
  DECLINE_LABEL,
  NO_DEBT_TEXT,
  PROPOSAL_PRICE,
  STALE_DEBT_TEXT,
  debtLine,
  isStale,
  profileLine,
  weekBlockedLine,
} from '@/lib/day-profiles';

const accepted = mock(() => Promise.resolve());
const declined = mock(() => Promise.resolve());

function offer(overrides: Partial<Offer> = {}): Offer {
  return {
    profile_code: 'deadline',
    title: 'Неделя сдачи',
    work_cap_min: 720,
    valid_from: '2026-08-31',
    valid_to: '2026-09-04',
    reason: 'до 2026-09-04 дедлайн «Payment-сервис», и 3 из последних семи дней уже вышли за базовый потолок',
    source_signal_id: 'CU-1',
    ...overrides,
  };
}

function withProposal(proposal: Offer | null) {
  mock.module('@/hooks/useProfileProposal', () => ({
    LOAD_PROPOSAL_ERROR: 'Не удалось прочитать предложение по потолку',
    useProfileProposal: () => ({
      proposal,
      saving: false,
      error: null,
      accept: accepted,
      decline: declined,
    }),
  }));
}

function debt(overrides: Partial<OvertimeDebt> = {}): OvertimeDebt {
  return {
    incurred_on: '2026-08-31',
    minutes_over: 180,
    repaid_on: null,
    repaid_by_day: null,
    is_open: true,
    days_open: 2,
    ...overrides,
  };
}

function week(overrides: Partial<Week> = {}): Week {
  return {
    iso_code: '2026-W36',
    starts_on: '2026-08-31',
    ends_on: '2026-09-06',
    won_days: 7,
    total_days: 7,
    streak_end: 7,
    debt_minutes: 0,
    is_won: true,
    retro_md: '',
    blockers_md: '',
    mgmt_retro_md: '',
    weekly_number_md: '',
    review_items: [],
    computed_at: '2026-09-06T20:00:00Z',
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  accepted.mockClear();
  declined.mockClear();
});

describe('карточка предложения', () => {
  it('отсутствует, когда предлагать нечего', async () => {
    withProposal(null);
    const { default: ProfileProposalCard } = await import('./ProfileProposal');
    const { container } = render(<ProfileProposalCard />);
    expect(container.textContent).toBe('');
  });

  it('называет причину и цену в одном взгляде', async () => {
    withProposal(offer());
    const { default: ProfileProposalCard } = await import('./ProfileProposal');
    render(<ProfileProposalCard />);
    expect(screen.getByText(/Payment-сервис/)).toBeTruthy();
    expect(screen.getByText(PROPOSAL_PRICE)).toBeTruthy();
  });

  it('«принять» подтверждает подъём', async () => {
    withProposal(offer());
    const { default: ProfileProposalCard } = await import('./ProfileProposal');
    render(<ProfileProposalCard />);
    fireEvent.click(screen.getByText(ACCEPT_LABEL));
    expect(accepted).toHaveBeenCalled();
  });

  it('«нет» записывает отказ', async () => {
    withProposal(offer());
    const { default: ProfileProposalCard } = await import('./ProfileProposal');
    render(<ProfileProposalCard />);
    fireEvent.click(screen.getByText(DECLINE_LABEL));
    expect(declined).toHaveBeenCalled();
  });
});

describe('строка профиля дня', () => {
  it('молчит на обычном дне', () => {
    const baseline: ProfileInForce = {
      code: 'baseline',
      title: 'Обычная неделя',
      work_cap_min: 480,
      valid_to: null,
      reason: '',
    };
    expect(profileLine(baseline)).toBeNull();
    expect(profileLine(null)).toBeNull();
  });

  it('называет потолок и срок, когда подъём действует', () => {
    const raised: ProfileInForce = {
      code: 'deadline',
      title: 'Неделя сдачи',
      work_cap_min: 720,
      valid_to: '2026-09-04',
      reason: 'сдача',
    };
    expect(profileLine(raised)).toBe('Неделя сдачи: потолок 12 ч до 2026-09-04');
  });
});

describe('долг за переработку', () => {
  it('открытый долг называет дни, закрытый — дату возврата', () => {
    expect(debtLine(debt())).toBe('2026-08-31: 3 ч — 2 дня не возвращено');
    expect(
      debtLine(debt({ is_open: false, repaid_on: '2026-09-02', days_open: 2 }))
    ).toBe('2026-08-31: 3 ч — вернулось 2026-09-02');
  });

  it('долг старше недели — проваленное правило, а не справка', () => {
    expect(isStale(debt({ days_open: 8 }))).toBe(true);
    expect(isStale(debt({ days_open: 3 }))).toBe(false);
    expect(isStale(debt({ days_open: 30, is_open: false }))).toBe(false);
  });

  it('объясняет, почему неделя из выигранных дней не выиграна', () => {
    expect(weekBlockedLine(week())).toBeNull();
    expect(weekBlockedLine(week({ is_won: false, debt_minutes: 180 }))).toBe(
      'Неделя не выиграна: 3 ч переработки не вернулись.'
    );
  });

  it('блок рисует долги и молчит, когда их нет', async () => {
    mock.module('@/lib/api', () => ({
      profilesAPI: {
        proposal: () => Promise.resolve(null),
        activate: () => Promise.resolve(null),
        decline: () => Promise.resolve(null),
        debt: () => Promise.resolve({ open_minutes: 0, debts: [] }),
      },
    }));
    const { default: OvertimeDebtBlock } = await import('@/components/week/OvertimeDebt');
    render(<OvertimeDebtBlock week={week()} />);
    expect(screen.getByText(NO_DEBT_TEXT)).toBeTruthy();
    expect(screen.queryByText(STALE_DEBT_TEXT)).toBeNull();
  });
});
