// [review:need-review] PHASE-02/70, PHASE-03/303
// summary: render tests of the workouts section — the 30-day totals per kind (time, energy and distance only where HealthKit held them), the newest workouts as events with the phone's own start time and only the numbers HealthKit held (a missing one left out, not zero), the honest empty line, nothing before the answer — and the read of the 30-day window that a failure leaves out

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { HealthWorkout } from '@/lib/api';
import { localDate } from '@/lib/health-metrics';
import { nightLabel } from './SleepSection';
import WorkoutsSection, {
  WORKOUTS_EMPTY_TEXT,
  activeTime,
  totalDetails,
  workoutDetails,
  workoutDistance,
  workoutsCount,
} from './WorkoutsSection';
import { workoutTotals } from '@/lib/health-visual';
import { shiftDate } from './useSleepNights';
import { useWorkouts } from './useWorkouts';

afterEach(cleanup);

const RUN: HealthWorkout = {
  id: '5f1e0c2a-0000-4000-8000-000000000001',
  activity_type: 'running',
  activity_label: 'Бег',
  date: '2026-10-20',
  start: '2026-10-20T18:00:00+02:00',
  end: '2026-10-20T18:45:00+02:00',
  duration_min: 45,
  energy_kcal: 410.5,
  distance_m: 7200,
  avg_heart_rate: 152,
  max_heart_rate: 178,
};

const YOGA: HealthWorkout = {
  ...RUN,
  id: '5f1e0c2a-0000-4000-8000-000000000002',
  activity_type: 'yoga',
  activity_label: 'Йога',
  date: '2026-10-19',
  start: '2026-10-19T07:30:00+02:00',
  end: '2026-10-19T08:00:00+02:00',
  duration_min: 30,
  energy_kcal: null,
  distance_m: null,
  avg_heart_rate: null,
  max_heart_rate: null,
};

describe('workout wording', () => {
  it('says kilometres from a kilometre up and metres below it', () => {
    expect(workoutDistance(7200)).toBe('7,2 км');
    expect(workoutDistance(850)).toBe('850 м');
  });

  it('lists only the numbers HealthKit held', () => {
    expect(workoutDetails(RUN)).toEqual(['7,2 км', '411 ккал', 'пульс 152 уд/мин', 'макс. 178']);
    expect(workoutDetails(YOGA)).toEqual([]);
  });
});

describe('workout totals', () => {
  it('keeps a number HealthKit never held as null, not zero', () => {
    expect(workoutTotals([YOGA])).toEqual([
      { key: 'yoga', label: 'Йога', count: 1, minutes: 30, energyKcal: null, distanceM: null },
    ]);
    expect(totalDetails(workoutTotals([YOGA])[0])).toEqual(['30 мин']);
  });

  it('puts the longest-trained kind first and sums what was held', () => {
    const totals = workoutTotals([YOGA, RUN, RUN]);
    expect(totals.map((total) => total.key)).toEqual(['running', 'yoga']);
    expect(totals[0]).toMatchObject({ count: 2, minutes: 90, energyKcal: 821, distanceM: 14400 });
  });

  it('says minutes up to two hours and hours after it', () => {
    expect(activeTime(62)).toBe('62 мин');
    expect(activeTime(200)).toBe('3 ч 20 мин');
  });

  it('declines the count of workouts', () => {
    expect([1, 2, 5, 11, 21, 24].map(workoutsCount)).toEqual([
      '1 тренировка',
      '2 тренировки',
      '5 тренировок',
      '11 тренировок',
      '21 тренировка',
      '24 тренировки',
    ]);
  });
});

describe('WorkoutsSection', () => {
  it('renders nothing before the first answer', () => {
    const { container } = render(<WorkoutsSection workouts={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('says no workout arrived instead of a zero', () => {
    render(<WorkoutsSection workouts={[]} />);
    expect(screen.getByRole('status').textContent).toBe(WORKOUTS_EMPTY_TEXT);
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('lists the workouts newest first as events', () => {
    render(<WorkoutsSection workouts={[YOGA, RUN]} />);

    expect(screen.getByRole('heading', { name: 'Тренировки' })).toBeDefined();
    const rows = screen.getByRole('list', { name: 'Последние тренировки' }).querySelectorAll('li');
    expect([...rows].map((row) => row.textContent)).toEqual([
      `Бег45 мин${nightLabel('2026-10-20')}, 18:00 · 7,2 км · 411 ккал · пульс 152 уд/мин · макс. 178`,
      `Йога30 мин${nightLabel('2026-10-19')}, 07:30`,
    ]);
  });

  it('sums the 30 days per kind and prints energy and distance only where they were held', () => {
    render(<WorkoutsSection workouts={[YOGA, RUN, { ...RUN, id: 'second-run' }]} />);

    expect(screen.getByText('За 30 дней: 3 тренировки · 2 ч')).toBeDefined();
    const rows = screen.getByRole('list', { name: 'Тренировки по видам' }).querySelectorAll('li');
    expect([...rows].map((row) => row.textContent)).toEqual([
      'Бег× 290 мин · 821 ккал · 14,4 км',
      'Йога× 130 мин',
    ]);
  });

  it('shows only the five newest workouts in the list', () => {
    const many = Array.from({ length: 8 }, (_, index) => ({ ...RUN, id: `run-${index}` }));
    render(<WorkoutsSection workouts={many} />);

    expect(
      screen.getByRole('list', { name: 'Последние тренировки' }).querySelectorAll('li')
    ).toHaveLength(5);
  });

  it('reads the start time on the phone clock, not the reader one', () => {
    render(<WorkoutsSection workouts={[{ ...RUN, start: '2026-10-20T18:00:00-04:00' }]} />);
    expect(screen.getByText(/, 18:00/)).toBeDefined();
  });
});

describe('useWorkouts', () => {
  it('asks for today and the 29 days before it', async () => {
    const asked: Array<[string, string]> = [];
    const read = (dateFrom: string, dateTo: string) => {
      asked.push([dateFrom, dateTo]);
      return Promise.resolve({ workouts: [RUN] });
    };

    const { result } = renderHook(() => useWorkouts(read));

    await waitFor(() => expect(result.current).toEqual([RUN]));
    const today = localDate();
    expect(asked).toEqual([[shiftDate(today, -29), today]]);
  });

  it('stays out after a failed read', async () => {
    let calls = 0;
    const read = () => {
      calls += 1;
      return Promise.reject(new Error('network down'));
    };

    const { result } = renderHook(() => useWorkouts(read));

    await waitFor(() => expect(calls).toBe(1));
    expect(result.current).toBeNull();
  });
});
