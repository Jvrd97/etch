// [review:need-review] PHASE-03/147, PHASE-03/148
// summary: tests for the mobile day screen — the day with no plan carries the same button out of it as the desktop shell does, the button is gone the moment there is a plan, and a plan the skeleton assembled says so and says why

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { DayDetail, PlanViolation } from '@/lib/api';
import { DAY, PLAN } from '@/test-fixtures/day';
import { BUILD_PLAN_LABEL } from '@/components/day/PlanBuilder';
import { FALLBACK_REASON_LABELS, planAuthorLabel } from '@/lib/plan-violations';

let state: {
  detail: DayDetail | null;
  loading: boolean;
  error: string | null;
  violations: PlanViolation[];
  reload: () => void;
};

// The hook rather than the API client: the shell's contract is the hook, and
// both shells are held to the same one.
mock.module('@/hooks/useDay', () => ({
  useDay: () => state,
}));

const { default: MobileDayScreen } = await import('./MobileDayScreen');

beforeEach(() => {
  state = { detail: DAY, loading: false, error: null, violations: [], reload: () => {} };
});

afterEach(() => {
  cleanup();
});

describe('MobileDayScreen и день без плана', () => {
  it('даёт тот же выход, что большой экран', () => {
    // Один компонент на оба шелла: телефон — это тот же день, а не его
    // урезанная версия, и собирать план с него можно ровно так же.
    render(<MobileDayScreen date="2026-08-30" />);

    expect(screen.getByText(BUILD_PLAN_LABEL)).toBeDefined();
  });

  it('убирает кнопку, как только план есть', () => {
    state = { ...state, detail: { ...DAY, plan: PLAN, has_plan: true } };
    render(<MobileDayScreen date="2026-08-30" />);

    expect(screen.queryByText(BUILD_PLAN_LABEL)).toBeNull();
    expect(screen.getByText('Воскресный блок')).toBeDefined();
  });

  it('называет скелет скелетом и говорит, почему не модель', () => {
    const skeleton = {
      ...PLAN,
      source: 'fallback' as const,
      fallback_reason: 'llm_timeout' as const,
    };
    state = { ...state, detail: { ...DAY, plan: skeleton, has_plan: true } };
    render(<MobileDayScreen date="2026-08-30" />);

    expect(screen.getByText(planAuthorLabel(skeleton))).toBeDefined();
    expect(
      screen.getByText(`Почему: ${FALLBACK_REASON_LABELS.llm_timeout}`)
    ).toBeDefined();
  });
});
