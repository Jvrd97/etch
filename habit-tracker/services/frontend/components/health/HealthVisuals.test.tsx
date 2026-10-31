// [review:need-review] PHASE-03/303
// summary: render tests of the Health visuals — the state card (word, number, the honest line under three days, a label with no word, nothing without the index), the steps and energy tiles, the seven sleep columns with the best night and an empty slot, the deviation bars with the «вне обычного» text, and the layout wrapper hiding each block without its data; plus the score hook

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { HealthMetric, HealthSleepNight } from '@/lib/api';
import { useHealthScore } from '@/hooks/useHealthScore';
import { localDate } from '@/lib/health-metrics';
import { shiftDate } from '@/lib/health';
import { DEVIATION_METRICS, ENERGY_IDENTIFIER, STEPS_IDENTIFIER } from '@/lib/health-visual';
import DeviationBars, { DEVIATION_NO_NORM_TEXT } from './DeviationBars';
import HealthStateCard, { SCORE_EMPTY_TEXT } from './HealthStateCard';
import HealthTiles from './HealthTiles';
import HealthVisuals from './HealthVisuals';
import SleepNightsChart from './SleepNightsChart';

afterEach(cleanup);

const TODAY = localDate();

function metric(identifier: string, overrides: Partial<HealthMetric> = {}): HealthMetric {
  return {
    identifier,
    kind: 'discrete',
    canonical_unit: 'count/min',
    display_name: identifier,
    group: 'heart',
    days: [{ date: TODAY, value: 58 }],
    baseline: null,
    ...overrides,
  };
}

function night(daysAgo: number, asleep: number): HealthSleepNight {
  const date = shiftDate(TODAY, -daysAgo);
  return {
    date,
    bedtime: `${date}T00:10:00+02:00`,
    wake_time: `${date}T07:40:00+02:00`,
    in_bed_min: asleep + 20,
    asleep_min: asleep,
    awake_min: 20,
    core_min: asleep - 150,
    deep_min: 60,
    rem_min: 90,
    unspecified_min: 0,
  };
}

describe('HealthStateCard', () => {
  it('prints the word, the number out of 100 and the days it stands on', () => {
    render(<HealthStateCard score={{ value: 78, label: 'good', basis_days: 7 }} />);

    expect(screen.getByRole('heading', { name: 'Состояние сегодня' })).toBeDefined();
    expect(screen.getByText('Хорошее')).toBeDefined();
    expect(screen.getByText('78')).toBeDefined();
    expect(screen.getByText('из 100')).toBeDefined();
    expect(screen.getByText('Индекс по 7 дням данных')).toBeDefined();
  });

  it('says why there is no number under three days instead of drawing a zero', () => {
    render(<HealthStateCard score={{ value: null, label: null, basis_days: 2 }} />);

    expect(screen.getByRole('status').textContent).toBe(SCORE_EMPTY_TEXT);
    expect(screen.queryByText('из 100')).toBeNull();
  });

  it('prints the number alone for a label it has no word for', () => {
    render(<HealthStateCard score={{ value: 41, label: 'brand-new', basis_days: 5 }} />);

    expect(screen.getByText('41')).toBeDefined();
    expect(screen.queryByText('Хорошее')).toBeNull();
  });

  it('renders nothing without the index', () => {
    const { container } = render(<HealthStateCard score={null} />);
    expect(container.innerHTML).toBe('');
  });
});

describe('HealthTiles', () => {
  it('shows steps and energy with the latest number and the 30-day mean, linked to the detail', () => {
    render(
      <HealthTiles
        basePath="/health"
        metrics={[
          metric(STEPS_IDENTIFIER, {
            canonical_unit: 'count',
            days: [
              { date: shiftDate(TODAY, -1), value: 8000 },
              { date: TODAY, value: 14220 },
            ],
          }),
          metric(ENERGY_IDENTIFIER, { canonical_unit: 'kcal', days: [] }),
        ]}
      />
    );

    expect(screen.getByRole('link', { name: /Шаги/ }).getAttribute('href')).toBe(
      `/health/${STEPS_IDENTIFIER}`
    );
    expect(screen.getByText(/14\s220/)).toBeDefined();
    expect(screen.getByText(/в среднем 11\s110 за 30 дн\./)).toBeDefined();
    expect(screen.getByText('Пока нет данных')).toBeDefined();
  });

  it('leaves a tile out when the catalog does not hold the metric', () => {
    const { container } = render(<HealthTiles basePath="/health" metrics={[metric('other')]} />);
    expect(container.innerHTML).toBe('');
  });
});

describe('SleepNightsChart', () => {
  it('renders nothing before the first answer', () => {
    const { container } = render(<SleepNightsChart nights={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('says no night arrived instead of drawing empty bars', () => {
    render(<SleepNightsChart nights={[]} />);
    expect(screen.getByRole('status')).toBeDefined();
    expect(screen.queryByRole('list', { name: 'Ночи недели' })).toBeNull();
  });

  it('lists seven nights by wake date, names the longest one and keeps a missing night as a gap', () => {
    render(
      <SleepNightsChart nights={[night(3, 400), night(1, 480), night(0, 430)]} detailHref="/health/sleep" />
    );

    expect(screen.getByRole('heading', { name: 'Сон по ночам' })).toBeDefined();
    const rows = screen.getByRole('list', { name: 'Ночи недели' }).querySelectorAll('li');
    expect(rows).toHaveLength(7);
    expect(rows[5].textContent).toContain('лучшая ночь');
    expect(rows[5].textContent).toContain('8 ч');
    expect(rows[4].textContent).toContain('ночи нет');
    expect(screen.getByText(/отбой 00:10, подъём 07:40/)).toBeDefined();
    expect(screen.getByRole('link', { name: 'Все ночи' }).getAttribute('href')).toBe('/health/sleep');
  });
});

describe('DeviationBars', () => {
  const [resting, hrv, breathing] = DEVIATION_METRICS;

  it('draws the three metrics against their own norm, in words as well as in colour', () => {
    render(
      <DeviationBars
        metrics={[
          metric(resting.identifier, {
            baseline: { mean: 56, stddev: 2, days: 20, day: TODAY, deviation: 4, outside_typical: true },
          }),
          metric(hrv.identifier, {
            canonical_unit: 'ms',
            baseline: { mean: 50, stddev: 5, days: 20, day: TODAY, deviation: 0, outside_typical: false },
          }),
          metric(breathing.identifier, { canonical_unit: 'count/min' }),
        ]}
      />
    );

    expect(screen.getByRole('heading', { name: 'Отклонение от вашей нормы' })).toBeDefined();
    const items = screen.getAllByRole('listitem').map((item) => item.textContent);
    expect(items[0]).toContain('+4 уд/мин к обычному, вне обычного');
    expect(items[1]).toContain('как обычно');
    expect(items[2]).toContain(DEVIATION_NO_NORM_TEXT);
  });

  it('renders nothing when the catalog holds none of the three', () => {
    const { container } = render(<DeviationBars metrics={[metric('other')]} />);
    expect(container.innerHTML).toBe('');
  });
});

describe('HealthVisuals', () => {
  it('shows only the blocks that have their data', () => {
    render(
      <HealthVisuals
        score={null}
        metrics={null}
        nights={null}
        workouts={[]}
        basePath="/health"
        sleepDetailHref="/health/sleep"
      />
    );

    expect(screen.queryByRole('heading', { name: 'Состояние сегодня' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Сон по ночам' })).toBeNull();
    expect(screen.getByRole('heading', { name: 'Тренировки' })).toBeDefined();
  });
});

describe('useHealthScore', () => {
  it('hands over the index of the server', async () => {
    const score = { value: 78, label: 'good', basis_days: 7 };
    const read = () => Promise.resolve({ scores: { health: score } });
    const { result } = renderHook(() => useHealthScore(read));
    await waitFor(() => expect(result.current).toEqual(score));
  });

  it('stays null when the endpoint is missing', async () => {
    let calls = 0;
    const read = () => {
      calls += 1;
      return Promise.reject(new Error('404'));
    };
    const { result } = renderHook(() => useHealthScore(read));
    await waitFor(() => expect(calls).toBe(1));
    expect(result.current).toBeNull();
  });
});
