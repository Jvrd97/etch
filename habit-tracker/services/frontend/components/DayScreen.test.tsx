// [review:need-review] PHASE-03/86
// summary: tests for the day screen — a day with no plan says so instead of rendering an empty page or an error, and the rule it is judged by is on the screen

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { DayDetail } from '@/lib/api';
import { NO_PLAN_TEXT } from '@/lib/day-format';

const DAY: DayDetail = {
  day: {
    date: '2026-08-30',
    kind: 'off',
    is_nocode: false,
    opened_at: null,
    last_touched_at: null,
  },
  rule: {
    id: 2,
    valid_from: '2026-08-17',
    valid_to: null,
    timezone: 'Europe/Berlin',
    day_start_hour: 4,
    work_cap_min: 480,
    work_hard_cap_min: 540,
    work_stop_at: '16:00:00',
    max_work_tasks: 4,
    tasks_required_ratio: '1.00',
    overtime_disqualifies: true,
    workdays: [1, 2, 3, 4, 5],
    nocode_days: [2, 4],
    required_anchors: ['подъём'],
    note_md: '',
  },
  plan: null,
  has_plan: false,
};

let state: {
  detail: DayDetail | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
};

// The hook rather than the API client: the screen's contract is the hook, and
// mocking one export keeps this suite out of the shared `@/lib/api` registry.
mock.module('@/hooks/useDay', () => ({
  useDay: () => state,
}));

const { default: DayScreen } = await import('./DayScreen');

beforeEach(() => {
  state = { detail: DAY, loading: false, error: null, reload: () => {} };
});

afterEach(() => {
  cleanup();
});

describe('DayScreen', () => {
  it('says "плана нет" on a day without a plan', () => {
    // The whole reason the endpoint answers instead of 404ing: an empty day is
    // an answer, and a blank screen would read as a broken one.
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText(NO_PLAN_TEXT)).toBeDefined();
  });

  it('shows the date and what kind of day it is', () => {
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText('2026-08-30')).toBeDefined();
    expect(screen.getByText('выходной')).toBeDefined();
  });

  it('explains which rule this day is counted by', () => {
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText('действует с 2026-08-17')).toBeDefined();
    expect(screen.getByText('8 ч в день')).toBeDefined();
  });

  it('marks a no-code day', () => {
    state = { ...state, detail: { ...DAY, day: { ...DAY.day, is_nocode: true } } };
    render(<DayScreen date="2026-09-01" />);

    expect(screen.getByText('no-code day')).toBeDefined();
  });

  it('keeps the plan block away once a plan exists', () => {
    state = { ...state, detail: { ...DAY, has_plan: true } };
    render(<DayScreen date="2026-08-30" />);

    expect(screen.queryByText(NO_PLAN_TEXT)).toBeNull();
  });

  it('shows the failure instead of an empty day', () => {
    state = { detail: null, loading: false, error: 'нет правила', reload: () => {} };
    render(<DayScreen date="1999-01-01" />);

    expect(screen.getByText('нет правила')).toBeDefined();
  });
});
