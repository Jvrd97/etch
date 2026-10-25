// [review:need-review] PHASE-03/147, PHASE-03/148, PHASE-03/164
// summary: PHASE-03/164 — the agent banner stands on today's screen when the agent is silent and is absent on any other day
// summary: tests for the mobile day screen — the day with no plan carries the same button out of it as the desktop shell does, the button is gone the moment there is a plan, and a plan the skeleton assembled says so and says why

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { AgentStatus, DayDetail, PlanViolation } from '@/lib/api';
import { todayISO } from '@/lib/date';
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

// The agent banner reads its own hook; a status of null draws nothing, so the
// other suites that render this screen are not touched by it.
let agent: AgentStatus | null = null;
mock.module('@/hooks/useAgentStatus', () => ({
  useAgentStatus: () => agent,
}));

const { default: MobileDayScreen } = await import('./MobileDayScreen');

beforeEach(() => {
  agent = null;
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

const SILENT_THREE_HOURS: AgentStatus = {
  silence_threshold_seconds: 1800,
  agents: [
    {
      agent_id: '6f1b2c3d-0000-4000-8000-00000000a001',
      agent_version: '0.3.0',
      reported_at: '2026-10-25T09:00:00Z',
      accessibility_granted: true,
      titles_enabled: true,
      sampling_seconds: 5,
      queue_depth: 0,
      last_flush_at: null,
      last_error: null,
      silent_for_seconds: 3 * 3600,
      is_silent: true,
    },
  ],
};

describe('MobileDayScreen and the agent banner', () => {
  it('says the agent is silent on the screen of today', () => {
    agent = SILENT_THREE_HOURS;
    const today = todayISO();
    state = { ...state, detail: { ...DAY, day: { ...DAY.day, date: today } } };
    render(<MobileDayScreen date={today} />);

    expect(screen.getByText('Агент молчит 3 ч')).toBeDefined();
  });

  it('stays out of the way on any other day', () => {
    agent = SILENT_THREE_HOURS;
    render(<MobileDayScreen date="2026-08-30" />);

    expect(screen.queryByText(/Агент молчит/)).toBeNull();
  });
});
