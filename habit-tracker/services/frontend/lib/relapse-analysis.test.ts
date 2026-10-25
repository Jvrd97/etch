// [review:need-review] PHASE-01/207
// summary: tests for the relapse analysis — trailing week/month counts, average gap, Monday-first weekday split, the month-over-month trend and its not-enough-data guard, and the day/week buckets of the history chart

import { describe, expect, it } from 'bun:test';
import {
  formatDayCount,
  formatGap,
  formatRelapseDay,
  formatShortDay,
  formatWeekday,
  relapseTimeline,
  summarizeRelapses,
} from './relapse-analysis';

// A Saturday, so the weekday maths has something to get wrong.
const TODAY = '2026-10-24';

describe('summarizeRelapses', () => {
  it('counts relapse days in the trailing week and month, today included', () => {
    const summary = summarizeRelapses(
      ['2026-09-24', '2026-09-25', '2026-10-18', '2026-10-24'],
      '2026-01-01',
      TODAY
    );

    // 09-24 is 30 days before today and falls out; 09-25 is the first day in.
    expect(summary.lastMonth).toBe(3);
    // 10-18 is the first day of the week window.
    expect(summary.lastWeek).toBe(2);
  });

  it('counts a day once however many relapses it held', () => {
    const summary = summarizeRelapses(['2026-10-24', '2026-10-24'], '2026-10-01', TODAY);

    expect(summary.lastWeek).toBe(1);
    expect(summary.weekdays.reduce((a, b) => a + b, 0)).toBe(1);
  });

  it('averages the gaps between consecutive relapse days', () => {
    // Gaps of 3 and 6 days, given out of order.
    const summary = summarizeRelapses(['2026-10-10', '2026-10-01', '2026-10-04'], null, TODAY);

    expect(summary.averageGapDays).toBe(4.5);
  });

  it('has no average gap below two relapse days', () => {
    expect(summarizeRelapses([], null, TODAY).averageGapDays).toBeNull();
    expect(summarizeRelapses(['2026-10-01'], null, TODAY).averageGapDays).toBeNull();
  });

  it('splits relapse days by weekday, Monday first', () => {
    // 2026-10-19 is a Monday, 10-24 a Saturday, 10-25 a Sunday.
    const summary = summarizeRelapses(['2026-10-19', '2026-10-24', '2026-10-25', '2026-10-12'], null, '2026-10-25');

    expect(summary.weekdays).toEqual([2, 0, 0, 0, 0, 1, 1]);
  });

  it('says fewer when this month had fewer relapse days than the month before', () => {
    const summary = summarizeRelapses(
      ['2026-08-30', '2026-09-01', '2026-09-10', '2026-10-20'],
      '2026-08-01',
      TODAY
    );

    expect(summary.trend).toEqual({ kind: 'fewer', current: 1, previous: 3 });
  });

  it('says more and same the same way', () => {
    expect(
      summarizeRelapses(['2026-10-01', '2026-10-02'], '2026-08-01', TODAY).trend
    ).toEqual({ kind: 'more', current: 2, previous: 0 });
    expect(summarizeRelapses([], '2026-08-01', TODAY).trend).toEqual({
      kind: 'same',
      current: 0,
      previous: 0,
    });
  });

  it('refuses a trend until the history covers the month before too', () => {
    // The previous window starts on 2026-08-26; tracking began a day later.
    expect(summarizeRelapses(['2026-10-01'], '2026-08-27', TODAY).trend).toEqual({
      kind: 'not-enough-data',
    });
    expect(summarizeRelapses(['2026-10-01'], '2026-08-26', TODAY).trend.kind).toBe('more');
    expect(summarizeRelapses([], null, TODAY).trend).toEqual({ kind: 'not-enough-data' });
  });
});

describe('relapseTimeline', () => {
  it('draws one bar per day up to ninety days, ending today', () => {
    const timeline = relapseTimeline(['2026-10-01', '2026-10-24', '2026-09-01'], null, TODAY, '30d');

    expect(timeline.granularity).toBe('day');
    expect(timeline.buckets).toHaveLength(30);
    expect(timeline.buckets[0].start).toBe('2026-09-25');
    expect(timeline.buckets[29]).toEqual({ start: TODAY, end: TODAY, relapseDays: 1 });
    expect(timeline.buckets.filter((bucket) => bucket.relapseDays > 0).map((b) => b.start)).toEqual([
      '2026-10-01',
      '2026-10-24',
    ]);
  });

  it('switches to Monday weeks past ninety days and counts only days of the period', () => {
    const timeline = relapseTimeline(
      ['2025-10-24', '2025-10-25', '2026-10-19', '2026-10-20', '2026-10-24'],
      null,
      TODAY,
      '365d'
    );

    expect(timeline.granularity).toBe('week');
    // The period starts on Saturday 2025-10-25, so the first week starts on Monday 10-20
    // and holds only 10-25: 10-24 is a day before the period.
    expect(timeline.buckets[0]).toEqual({ start: '2025-10-20', end: '2025-10-26', relapseDays: 1 });
    const last = timeline.buckets[timeline.buckets.length - 1];
    expect(last).toEqual({ start: '2026-10-19', end: '2026-10-25', relapseDays: 3 });
    const total = timeline.buckets.reduce((sum, bucket) => sum + bucket.relapseDays, 0);
    expect(total).toBe(4);
  });

  it('starts the whole history at the first tracked day or the first relapse', () => {
    const fromTracking = relapseTimeline(['2026-10-20'], '2026-10-10', TODAY, 'all');
    expect(fromTracking.buckets[0].start).toBe('2026-10-10');
    expect(fromTracking.buckets).toHaveLength(15);

    const fromRelapse = relapseTimeline(['2026-10-05'], '2026-10-10', TODAY, 'all');
    expect(fromRelapse.buckets[0].start).toBe('2026-10-05');

    const empty = relapseTimeline([], null, TODAY, 'all');
    expect(empty.buckets).toEqual([{ start: TODAY, end: TODAY, relapseDays: 0 }]);
  });
});

describe('date labels', () => {
  it('renders a day the same way on every machine', () => {
    expect(formatRelapseDay('2026-10-05')).toBe('5 окт 2026');
    expect(formatShortDay('2026-10-05')).toBe('05.10');
    expect(formatWeekday('2026-10-05')).toBe('Пн');
    expect(formatWeekday('2026-10-04')).toBe('Вс');
  });

  it('declines day counts and keeps a fractional gap readable', () => {
    expect(formatDayCount(1)).toBe('1 день');
    expect(formatDayCount(4)).toBe('4 дня');
    expect(formatDayCount(11)).toBe('11 дней');
    expect(formatDayCount(21)).toBe('21 день');
    expect(formatGap(17)).toBe('17 дней');
    expect(formatGap(4.5)).toBe('4,5 дня');
  });
});
