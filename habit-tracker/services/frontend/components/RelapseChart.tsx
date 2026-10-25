'use client';
// [review:need-review] PHASE-01/207
// summary: history chart of an avoid category — recharts bars of relapse days per day (up to 90 days) or per Monday week, with the period switch and a text summary for screen readers

import { useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import {
  RELAPSE_PERIODS,
  RELAPSE_PERIOD_LABELS,
  RELAPSE_PERIOD_PHRASES,
  formatDayCount,
  formatRelapseDay,
  formatShortDay,
  relapseTimeline,
  type RelapseBucket,
  type RelapsePeriod,
} from '@/lib/relapse-analysis';

const CHART_HEIGHT_PX = 220;
const DEFAULT_PERIOD: RelapsePeriod = '90d';
const GRID_COLOR = 'rgba(255, 255, 255, 0.06)';
const AXIS_TICK_COLOR = '#a3a3a3';
// `--color-danger`: a relapse bar is the one thing on the page that is bad news.
const BAR_COLOR = '#ef4444';
const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];
const MAX_BAR_PX = 18;
const TOOLTIP_STYLE: React.CSSProperties = {
  backgroundColor: '#141414',
  border: '1px solid rgba(255, 255, 255, 0.1)',
  borderRadius: '12px',
  color: '#f5f5f5',
};

interface RelapseChartProps {
  relapseDates: readonly string[];
  trackedSince: string | null;
  today: string;
}

export default function RelapseChart({ relapseDates, trackedSince, today }: RelapseChartProps) {
  const [period, setPeriod] = useState<RelapsePeriod>(DEFAULT_PERIOD);
  const timeline = useMemo(
    () => relapseTimeline(relapseDates, trackedSince, today, period),
    [relapseDates, trackedSince, today, period]
  );
  const total = timeline.buckets.reduce((sum, bucket) => sum + bucket.relapseDays, 0);
  const byStart = useMemo(
    () => new Map(timeline.buckets.map((bucket) => [bucket.start, bucket])),
    [timeline]
  );

  const describe = (start: string): string => {
    const bucket: RelapseBucket | undefined = byStart.get(start);
    if (bucket === undefined) return start;
    if (timeline.granularity === 'day') return formatRelapseDay(bucket.start);
    return `Неделя с ${formatRelapseDay(bucket.start)}`;
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Период графика срывов">
        {RELAPSE_PERIODS.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setPeriod(option)}
            aria-pressed={option === period}
            className={`min-h-11 px-4 py-2 rounded-full text-sm font-medium transition-all duration-200 border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime ${
              option === period
                ? 'bg-lime text-background border-lime'
                : 'bg-surface text-text-secondary border-white/10 hover:text-text-primary hover:bg-white/5'
            }`}
          >
            {RELAPSE_PERIOD_LABELS[option]}
          </button>
        ))}
      </div>

      <div
        role="img"
        aria-label={`График срывов ${RELAPSE_PERIOD_PHRASES[period]}: ${formatDayCount(total)} со срывом`}
        style={{ height: CHART_HEIGHT_PX }}
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={timeline.buckets} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID_COLOR} vertical={false} />
            <XAxis
              dataKey="start"
              tickFormatter={formatShortDay}
              tick={{ fill: AXIS_TICK_COLOR, fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: GRID_COLOR }}
              minTickGap={24}
            />
            <YAxis
              // A day bar is 0 or 1: an axis would only say so twice, and the
              // fixed domain lets a relapse day fill the height instead of a quarter.
              hide={timeline.granularity === 'day'}
              domain={timeline.granularity === 'day' ? [0, 1] : [0, 'auto']}
              allowDecimals={false}
              tick={{ fill: AXIS_TICK_COLOR, fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={32}
            />
            <Tooltip
              cursor={{ fill: 'rgba(255, 255, 255, 0.04)' }}
              contentStyle={TOOLTIP_STYLE}
              labelStyle={{ color: AXIS_TICK_COLOR }}
              labelFormatter={(label) => describe(String(label))}
              formatter={(value) => {
                const days = Number(value);
                if (timeline.granularity === 'day') {
                  return [days > 0 ? 'был срыв' : 'без срыва', ''];
                }
                return [`${formatDayCount(days)} со срывом`, ''];
              }}
              separator=""
            />
            <Bar dataKey="relapseDays" fill={BAR_COLOR} radius={BAR_RADIUS} maxBarSize={MAX_BAR_PX} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
