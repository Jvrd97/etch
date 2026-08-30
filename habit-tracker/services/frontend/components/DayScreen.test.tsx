// [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/88, PHASE-03/90, PHASE-03/94
// summary: tests for the day screen — a day with no plan says so instead of rendering an empty page or an error, the rule it is judged by is on the screen, a day nobody opened says so, and the notebook and the итог of the day are there

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { DayDetail, Plan } from '@/lib/api';
import { NOTEBOOK_TITLE } from '@/components/day/DayNotebook';
import { NO_PLAN_TEXT } from '@/lib/day-format';
import { DAY_NEVER_OPENED } from '@/lib/marks';

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
  marks: [],
  task_counts: { planned: 0, done: 0, failed: 0, skipped: 0, pending: 0 },
  notebook: null,
  summary: {
    day_date: '2026-08-30',
    closed: false,
    stage: 'open' as const,
    reviewed_at: null,
    review_skipped: false,
    rule_set_id: 2,
    verdict: null,
    verdict_reason: 'not_closed',
    verdict_override: false,
    verdict_override_note: null,
    anchors_done: 0,
    anchors_total: 0,
    tasks_done: 0,
    tasks_total: 0,
    work_minutes: null,
    streak_after: null,
    wrote_from_scratch: null,
    education_debt: null,
    reviewed_today: null,
    body_md: '',
    missing_data: ['work_minutes'],
    missing_anchors: [],
    source: 'close',
  },
  work: {
    day_date: '2026-08-30',
    intervals: [],
    // «Не измерено», not zero: the day has no intervals at all.
    work_minutes: null,
    running: false,
  },
};

// A plan as the server answers with one: sections in order, a schedule the
// server measured, and no collisions.
const PLAN: Plan = {
  id: 'p1',
  day_date: '2026-08-30',
  title: 'План 2026-08-30 (вс)',
  title_marker: null,
  lede: 'Выходной по канону',
  purpose_md: null,
  quarter_goal_id: null,
  counters: [],
  condition_tomorrow: null,
  status: 'active',
  source: 'day-open',
  created_at: '2026-08-30T06:00:00Z',
  updated_at: '2026-08-30T06:00:00Z',
  sections: [
    {
      id: 's1',
      ord: 0,
      title: 'Воскресный блок',
      kind: 'personal',
      items: [
        {
          id: 'i1',
          parent_id: null,
          ord: 0,
          kind: 'bullet',
          rigidity: 'soft',
          text_md: 'Недельное ретро W35',
          text_plain: 'Недельное ретро W35',
          starts_at: '2026-08-30T09:00:00Z',
          ends_at: '2026-08-30T09:40:00Z',
          window_comment: null,
          code: null,
          done_criterion: null,
          why_md: null,
          plan_md: null,
          external_ref: null,
          extra: {},
          quarter_goal_id: null,
          unlinked_reason: null,
          carried_from_item_id: null,
          carry_count: 0,
          children: [],
        },
      ],
    },
  ],
  schedule: [
    {
      item_id: 'i1',
      section_id: 's1',
      code: null,
      text_plain: 'Недельное ретро W35',
      kind: 'bullet',
      rigidity: 'soft',
      starts_at: '2026-08-30T09:00:00Z',
      ends_at: '2026-08-30T09:40:00Z',
      minutes: 40,
      window_comment: null,
    },
  ],
  overlaps: [],
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

// The screen carries the shared day navigation since `#94`; it fetches a range
// of its own, and this test is about the day rather than about the list beside it.
mock.module('@/hooks/useDays', () => ({
  useDays: () => ({ days: [], loading: false, error: null, reload: () => {} }),
  LOAD_DAYS_ERROR: 'Не удалось загрузить дни',
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

  it('renders the plan instead of the "плана нет" block once there is one', () => {
    state = { ...state, detail: { ...DAY, plan: PLAN, has_plan: true } };
    render(<DayScreen date="2026-08-30" />);

    expect(screen.queryByText(NO_PLAN_TEXT)).toBeNull();
    expect(screen.getByText('Воскресный блок')).toBeDefined();
    expect(screen.getByText('Расписание дня')).toBeDefined();
  });

  it('says how many work tasks the plan spends of the bar', () => {
    // The bar is the rule's, not a constant: a day under the legacy canon is
    // read against different numbers, and the screen has to show which.
    state = { ...state, detail: { ...DAY, plan: PLAN, has_plan: true } };
    render(<DayScreen date="2026-08-30" />);

    expect(
      screen.getByText(/Рабочих задач: 0 из 4 · закрыто 0 из 0/)
    ).toBeDefined();
  });

  it('says outright when nobody has opened the day', () => {
    // One of the four kinds of empty `#88` separates: a day with no marks that
    // nobody ever came to is not a day where nothing was done.
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText(DAY_NEVER_OPENED)).toBeDefined();
  });

  it('keeps that badge off a day that was opened', () => {
    state = {
      ...state,
      detail: { ...DAY, day: { ...DAY.day, opened_at: '2026-08-30T07:10:00Z' } },
    };
    render(<DayScreen date="2026-08-30" />);

    expect(screen.queryByText(DAY_NEVER_OPENED)).toBeNull();
  });

  it('offers the notebook of the day', () => {
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByLabelText(NOTEBOOK_TITLE)).toBeDefined();
  });

  it('shows the failure instead of an empty day', () => {
    state = { detail: null, loading: false, error: 'нет правила', reload: () => {} };
    render(<DayScreen date="1999-01-01" />);

    expect(screen.getByText('нет правила')).toBeDefined();
  });
});
