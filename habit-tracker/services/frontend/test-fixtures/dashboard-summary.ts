// [review:need-review] #302
// summary: dashboard summary answers built by the contract of #296 - a full week, a full month and an empty window - for the tests of the hook, the blocks and the screen

import type { DashboardPeriod, DashboardSummary } from '@/lib/api';

export function fullSummary(period: DashboardPeriod = 'week'): DashboardSummary {
  const dayCount = period === 'week' ? 7 : 30;
  const days = (pattern: Array<boolean | null>) =>
    Array.from({ length: dayCount }, (_, index) => pattern[index % pattern.length]);
  return {
    period,
    from: period === 'week' ? '2026-10-25' : '2026-10-02',
    to: '2026-10-31',
    today: '2026-10-31',
    scores: {
      health: { value: 78, label: 'good', basis_days: 7 },
      habits: { value: 64, done: 45, total: 70 },
      challenges: { done: 3, total: 5 },
    },
    streaks: [
      {
        category_id: 1,
        name: 'Холодный душ',
        kind: 'build',
        current: 12,
        best: 21,
        days: days([true, true, true, true, true, false, true]),
      },
      {
        category_id: 2,
        name: 'Без сахара',
        kind: 'avoid',
        current: 1,
        best: 9,
        days: days([true, null, false, true]),
      },
    ],
    health: [
      {
        identifier: 'HKCategoryTypeIdentifierSleepAnalysis',
        label: 'Сон',
        value: 432,
        unit: 'min',
        baseline_delta: 20,
        higher_is_better: true,
      },
      {
        identifier: 'HKQuantityTypeIdentifierRestingHeartRate',
        label: 'Пульс покоя',
        value: 58,
        unit: 'count/min',
        baseline_delta: -2,
        higher_is_better: false,
      },
      {
        identifier: 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN',
        label: 'Вариабельность пульса',
        value: 61.5,
        unit: 'ms',
        baseline_delta: 0,
        higher_is_better: true,
      },
    ],
    bests: [
      {
        identifier: 'HKQuantityTypeIdentifierStepCount',
        label: 'Шаги',
        value: 14220,
        unit: 'count',
        date: '2026-10-28',
        is_record: true,
      },
      {
        identifier: 'HKCategoryTypeIdentifierSleepAnalysis',
        label: 'Сон',
        value: 495,
        unit: 'min',
        date: '2026-10-20',
        is_record: false,
      },
    ],
    workouts: {
      weeks: [
        { week_start: '2026-10-05', count: 2, minutes: 90 },
        { week_start: '2026-10-12', count: 4, minutes: 200 },
        { week_start: '2026-10-19', count: 3, minutes: 140 },
      ],
      total: 9,
      delta_vs_previous: 1,
    },
    insight: {
      text: 'Сон дольше 7 часов совпал с пятью закрытыми привычками из семи.',
      generated_at: '2026-10-31T09:00:00+01:00',
    },
  };
}

/**
 * A window with no data at all, in the shape the server gives an empty base: the
 * three scores and the workouts are objects whose fields are null, never a bare null.
 */
export function emptySummary(period: DashboardPeriod = 'week'): DashboardSummary {
  return {
    ...fullSummary(period),
    scores: {
      health: { value: null, label: null, basis_days: 1 },
      habits: { value: null, done: null, total: null },
      challenges: { done: null, total: null },
    },
    streaks: [],
    health: [],
    bests: [],
    workouts: { weeks: [], total: null, delta_vs_previous: null },
    insight: null,
  };
}
