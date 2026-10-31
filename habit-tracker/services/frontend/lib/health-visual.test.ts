// [review:need-review] PHASE-03/303 (round 2)
// summary: tests of the Health screen visuals' arithmetic — the word of the index and the lit segments of its ring, the tile series, the position of a deviation on its track (constant history, clamping, too little history), the seven sleep bars with a gap and the best night, and the workout totals

import { describe, expect, it } from 'bun:test';
import type { HealthMetric, HealthSleepNight } from '@/lib/api';
import {
  DEVIATION_METRICS,
  RING_SEGMENTS,
  deviationRatio,
  deviationVerdict,
  deviationRows,
  litSegments,
  ringTicks,
  scoreWord,
  sleepBars,
  tileSeries,
} from './health-visual';

function metric(overrides: Partial<HealthMetric>): HealthMetric {
  return {
    identifier: 'x',
    kind: 'discrete',
    canonical_unit: 'count/min',
    display_name: 'X',
    group: 'heart',
    days: [{ date: '2026-10-30', value: 60 }],
    baseline: null,
    ...overrides,
  };
}

function night(date: string, asleep: number, deep = 60, rem = 60): HealthSleepNight {
  return {
    date,
    bedtime: `${date}T00:00:00+02:00`,
    wake_time: `${date}T07:00:00+02:00`,
    in_bed_min: asleep + 10,
    asleep_min: asleep,
    awake_min: 10,
    core_min: asleep - deep - rem,
    deep_min: deep,
    rem_min: rem,
    unspecified_min: 0,
  };
}

describe('index of the day', () => {
  it('has a word for the server labels and none for a label it does not know', () => {
    expect(scoreWord('good')).toEqual({ word: 'Хорошее', tone: 'good' });
    expect(scoreWord('fair')?.tone).toBe('warn');
    expect(scoreWord('something-new')).toBeNull();
    expect(scoreWord(null)).toBeNull();
  });

  it('lights the ring in proportion, at least one segment for a nonzero index', () => {
    expect(litSegments(0)).toBe(0);
    expect(litSegments(1)).toBe(1);
    expect(litSegments(50)).toBe(RING_SEGMENTS / 2);
    expect(litSegments(78)).toBe(19);
    expect(litSegments(100)).toBe(RING_SEGMENTS);
    expect(litSegments(140)).toBe(RING_SEGMENTS);
  });

  it('starts the ring at twelve o\'clock', () => {
    const [first] = ringTicks(RING_SEGMENTS, 60, 44, 56);
    expect(first).toEqual({ x1: 60, y1: 16, x2: 60, y2: 4 });
  });
});

describe('tile series', () => {
  it('has no number for a metric with no day, and a mean over the days it has', () => {
    expect(tileSeries(metric({ days: [] }))).toEqual({ latest: null, average: null, points: [] });
    const series = tileSeries(
      metric({
        days: [
          { date: '2026-10-29', value: 4000 },
          { date: '2026-10-30', value: 6000 },
        ],
      })
    );
    expect(series.latest).toEqual({ date: '2026-10-30', value: 6000 });
    expect(series.average).toBe(5000);
    expect(series.points).toHaveLength(30);
  });
});

describe('deviation bars', () => {
  it('puts a deviation on its track against the usual spread and clamps it', () => {
    expect(deviationRatio(0, 2)).toBe(0);
    expect(deviationRatio(2, 2)).toBe(0.5);
    expect(deviationRatio(-2, 2)).toBe(-0.5);
    expect(deviationRatio(9, 2)).toBe(1);
    expect(deviationRatio(-9, 2)).toBe(-1);
  });

  it('fills the track on any step away from a constant history', () => {
    expect(deviationRatio(0.1, 0)).toBe(1);
    expect(deviationRatio(-0.1, 0)).toBe(-1);
  });

  it('does not scale a bar by rounding noise', () => {
    expect(deviationRatio(1e-9, 0)).toBe(0);
    expect(deviationRatio(0.5, 1e-9)).toBe(1);
  });

  it('judges each metric by its own direction: lower pulse and breathing are better, higher HRV is better', () => {
    expect(deviationVerdict(-3, false)).toBe('better');
    expect(deviationVerdict(3, false)).toBe('worse');
    expect(deviationVerdict(3, true)).toBe('better');
    expect(deviationVerdict(-3, true)).toBe('worse');
    expect(deviationVerdict(0, true)).toBeNull();
    expect(deviationVerdict(0.04, false)).toBeNull();
  });

  it('colours resting pulse and HRV above and below the norm by that direction, amber only for worse', () => {
    const baseline = (deviation: number, stddev = 2) => ({
      mean: 50, stddev, days: 20, day: '2026-10-30', deviation, outside_typical: false,
    });
    const tones = (deviation: number, stddev?: number) =>
      deviationRows([
        metric({ identifier: DEVIATION_METRICS[0].identifier, baseline: baseline(deviation, stddev) }),
        metric({ identifier: DEVIATION_METRICS[1].identifier, baseline: baseline(deviation, stddev) }),
        metric({ identifier: DEVIATION_METRICS[2].identifier, baseline: baseline(deviation, stddev) }),
      ]).map((row) => row.tone);

    // resting pulse, HRV, breathing
    expect(tones(5)).toEqual(['warn', 'good', 'warn']);
    expect(tones(-5)).toEqual(['good', 'warn', 'good']);
    expect(tones(0)).toEqual(['good', 'good', 'good']);
    expect(tones(5, 0)).toEqual(['warn', 'good', 'warn']);
  });

  it('draws only the metrics the catalog holds with a day, and marks a missing norm', () => {
    const [resting] = DEVIATION_METRICS;
    const rows = deviationRows([
      metric({ identifier: resting.identifier }),
      metric({ identifier: 'unrelated' }),
      metric({ identifier: DEVIATION_METRICS[1].identifier, days: [] }),
    ]);
    expect(rows.map((row) => row.label)).toEqual(['Пульс покоя']);
    expect(rows[0].ratio).toBeNull();
  });

  it('turns warn when the day is beyond the usual spread', () => {
    const rows = deviationRows([
      metric({
        identifier: DEVIATION_METRICS[0].identifier,
        baseline: { mean: 58, stddev: 2, days: 20, day: '2026-10-30', deviation: 5, outside_typical: true },
      }),
    ]);
    expect(rows[0]).toMatchObject({ ratio: 1, tone: 'warn' });
  });
});

describe('sleep bars', () => {
  it('keeps a night that never arrived as an empty slot and marks the longest one', () => {
    const { bars } = sleepBars(
      [night('2026-10-28', 400), night('2026-10-30', 470), night('2026-10-29', 430)],
      '2026-10-30'
    );
    expect(bars).toHaveLength(7);
    expect(bars.map((bar) => bar.night === null)).toEqual([true, true, true, true, false, false, false]);
    expect(bars.filter((bar) => bar.isBest).map((bar) => bar.date)).toEqual(['2026-10-30']);
    expect(bars.at(-1)).toMatchObject({ deepRemMin: 120, lightMin: 350 });
  });

  it('names no best night among fewer than two', () => {
    const { bars } = sleepBars([night('2026-10-30', 470)], '2026-10-30');
    expect(bars.some((bar) => bar.isBest)).toBe(false);
  });

  it('never lets a short week look like a tall one', () => {
    expect(sleepBars([night('2026-10-30', 300)], '2026-10-30').scaleMin).toBe(480);
    expect(sleepBars([night('2026-10-30', 600)], '2026-10-30').scaleMin).toBe(600);
  });
});
