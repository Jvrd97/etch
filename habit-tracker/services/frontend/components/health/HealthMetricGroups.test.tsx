// [review:need-review] PHASE-02/69
// summary: render tests of the catalog rows — one formatter for the value, a 30-day sparkline with a gap kept as a gap, an empty sparkline for a metric without history, the deviation from the metric's own baseline only when a baseline exists, and no overall score

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { HealthMetric } from '@/lib/api';
import { localDate } from '@/lib/health-metrics';
import { deviationText, sparklinePoints } from '@/lib/health';
import HealthMetricGroups from './HealthMetricGroups';

afterEach(cleanup);

const HEART: HealthMetric = {
  identifier: 'heart',
  kind: 'discrete',
  canonical_unit: 'count/min',
  display_name: 'Пульс',
  group: 'heart',
  days: [
    { date: '2026-10-18', value: 60 },
    { date: '2026-10-20', value: 67.3333333 },
  ],
  baseline: { mean: 62, stddev: 2, days: 20, deviation: 5.3333333, outside_typical: true },
};

const STEPS: HealthMetric = {
  identifier: 'steps',
  kind: 'cumulative',
  canonical_unit: 'count',
  display_name: 'Шаги',
  group: 'movement',
  days: [{ date: '2026-10-20', value: 4321 }],
  baseline: null,
};

const WEIGHT: HealthMetric = {
  identifier: 'weight',
  kind: 'discrete',
  canonical_unit: 'kg',
  display_name: 'Вес',
  group: 'body',
  days: [],
  baseline: null,
};

function row(name: string): HTMLElement {
  return screen.getByRole('link', { name: new RegExp(name) });
}

describe('catalog rows', () => {
  it('prints the value with the one formatter and shows the deviation from the baseline', () => {
    render(<HealthMetricGroups metrics={[HEART, STEPS, WEIGHT]} basePath="/health" />);
    expect(screen.getByText('67.3 count/min')).toBeDefined();
    expect(screen.getByText('+5.3 count/min к обычному, вне обычного')).toBeDefined();
  });

  it('shows no deviation without a baseline, and no overall score', () => {
    render(<HealthMetricGroups metrics={[HEART, STEPS, WEIGHT]} basePath="/health" />);
    expect(row('Шаги').textContent).not.toContain('к обычному');
    expect(screen.queryByText(/здоровье \d+|общее состояние/i)).toBeNull();
  });

  it('draws a gap between days without data as two paths', () => {
    render(<HealthMetricGroups metrics={[HEART, STEPS, WEIGHT]} basePath="/health" />);
    expect(row('Пульс').querySelectorAll('svg path').length).toBe(2);
    expect(row('Шаги').querySelectorAll('svg path').length).toBe(1);
  });

  it('leaves the sparkline empty, not flat, for a metric without history', () => {
    render(<HealthMetricGroups metrics={[HEART, STEPS, WEIGHT]} basePath="/health" />);
    expect(row('Вес').querySelectorAll('svg path').length).toBe(0);
    expect(row('Вес').textContent).toContain('Нет данных');
  });
});

describe('a last value that is not today', () => {
  it('names its date, and says nothing for today', () => {
    const today: HealthMetric = {
      ...STEPS,
      days: [{ date: localDate(), value: 100 }],
    };
    render(<HealthMetricGroups metrics={[HEART, today]} basePath="/health" />);
    expect(row('Пульс').textContent).toContain('20 окт');
    expect(row('Шаги').textContent).not.toMatch(/окт|янв|февр|мар|апр|мая|июн|июл|авг|сент|нояб|дек/);
  });

  it('marks a deviation beyond the usual in words, not only in colour', () => {
    const calm: HealthMetric = {
      ...HEART,
      baseline: { ...HEART.baseline!, outside_typical: false },
    };
    render(<HealthMetricGroups metrics={[calm]} basePath="/health" />);
    expect(row('Пульс').textContent).not.toContain('вне обычного');
  });
});

describe('sparkline vocabulary', () => {
  it('lays 30 calendar days with null on a missing day', () => {
    const points = sparklinePoints(HEART.days, '2026-10-20');
    expect(points.length).toBe(30);
    expect(points[0].date).toBe('2026-09-21');
    expect(points.at(-1)).toEqual({ date: '2026-10-20', value: 67.3333333 });
    expect(points.at(-2)?.value).toBeNull();
  });

  it('gives no points without days', () => {
    expect(sparklinePoints([], '2026-10-20')).toEqual([]);
  });

  it('words the deviation by sign', () => {
    const base = { mean: 10, stddev: 1, days: 9, outside_typical: false };
    expect(deviationText({ ...base, deviation: -12.04 }, 'кг')).toBe('−12 кг к обычному');
    expect(deviationText({ ...base, deviation: 0.01 }, 'кг')).toBe('как обычно');
  });
});
