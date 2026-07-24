'use client';
// [review:need-review] PHASE-01/23-checklist-bar-streaks
// summary: category chart - line chart for form categories; for display_mode=checklist a done-count bar chart plus per-field current-streak badges

import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Category, TableDay } from '@/lib/api';
import {
  CHART_PERIODS,
  ChartPeriod,
  ChartSeries,
  PERIOD_LABELS,
  buildChartData,
  buildSeries,
  sliceByPeriod,
} from '@/lib/chart-data';
import {
  booleanFields,
  buildChecklistBarData,
  cumulate,
  currentStreak,
} from '@/lib/chart-utils';
import { todayISO } from '@/lib/date';

type ChartMode = 'perDay' | 'cumulative';

const CHART_MODES: readonly ChartMode[] = ['perDay', 'cumulative'];

const MODE_LABELS: Record<ChartMode, string> = {
  perDay: 'Per day',
  cumulative: 'Cumulative',
};

const CHART_HEIGHT_PX = 360;
const DEFAULT_PERIOD: ChartPeriod = '30d';
const GRID_COLOR = 'rgba(255, 255, 255, 0.06)';
const AXIS_TICK_COLOR = '#8a8a8a';
const TOOLTIP_STYLE: React.CSSProperties = {
  backgroundColor: '#141414',
  border: '1px solid rgba(255, 255, 255, 0.1)',
  borderRadius: '12px',
  color: '#f5f5f5',
};

const BAR_COLOR = '#b8ff36';
const BAR_RADIUS: [number, number, number, number] = [6, 6, 0, 0];

interface CategoryChartProps {
  category: Category;
  days: TableDay[];
}

export default function CategoryChart({ category, days }: CategoryChartProps) {
  return category.display_mode === 'checklist' ? (
    <ChecklistCategoryChart category={category} days={days} />
  ) : (
    <FormCategoryChart category={category} days={days} />
  );
}

interface PeriodButtonsProps {
  period: ChartPeriod;
  onChange: (period: ChartPeriod) => void;
}

function PeriodButtons({ period, onChange }: PeriodButtonsProps) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Chart period">
      {CHART_PERIODS.map((p) => (
        <button
          key={p}
          onClick={() => onChange(p)}
          aria-pressed={p === period}
          className={`px-4 py-2 rounded-full text-sm font-medium transition-all duration-200 border ${
            p === period
              ? 'bg-lime text-background border-lime shadow-[0_0_18px_rgba(184,255,54,0.25)]'
              : 'bg-surface text-text-secondary border-white/10 hover:text-text-primary hover:bg-white/5'
          }`}
        >
          {PERIOD_LABELS[p]}
        </button>
      ))}
    </div>
  );
}

function ChecklistCategoryChart({ category, days }: CategoryChartProps) {
  const [period, setPeriod] = useState<ChartPeriod>(DEFAULT_PERIOD);

  const boolFields = useMemo(() => booleanFields(category.fields), [category.fields]);
  const data = useMemo(
    () =>
      sliceByPeriod(buildChecklistBarData(days, category.id, boolFields), period),
    [days, category.id, boolFields, period]
  );
  const today = useMemo(() => todayISO(), []);
  const streaks = useMemo(
    () =>
      boolFields.map((field) => ({
        field,
        streak: currentStreak(days, category.id, field.id, today),
      })),
    [boolFields, days, category.id, today]
  );

  const total = boolFields.length;

  if (total === 0) {
    return (
      <div className="text-center py-16 bg-card border border-white/5 rounded-3xl">
        <p className="text-text-secondary">
          No boolean fields to chart in this category
        </p>
      </div>
    );
  }

  return (
    <div className="bg-card border border-white/5 rounded-3xl p-6 space-y-5">
      <PeriodButtons period={period} onChange={setPeriod} />

      <div className="flex flex-wrap gap-2" role="list" aria-label="Current streaks">
        {streaks.map(({ field, streak }) => (
          <div
            key={field.id}
            role="listitem"
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm bg-surface text-text-primary border border-white/10"
          >
            {field.name}
            <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-lime text-background">
              {streak} {streak === 1 ? 'day' : 'days'}
            </span>
          </div>
        ))}
      </div>

      <div style={{ height: CHART_HEIGHT_PX }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID_COLOR} vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fill: AXIS_TICK_COLOR, fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: GRID_COLOR }}
              minTickGap={24}
            />
            <YAxis
              domain={[0, total]}
              allowDecimals={false}
              tick={{ fill: AXIS_TICK_COLOR, fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={44}
            />
            <Tooltip
              cursor={{ fill: 'rgba(255, 255, 255, 0.04)' }}
              contentStyle={TOOLTIP_STYLE}
              formatter={(value) => [`${value} of ${total}`, 'Done']}
              labelStyle={{ color: '#8a8a8a' }}
            />
            <Bar dataKey="done" fill={BAR_COLOR} radius={BAR_RADIUS} maxBarSize={28} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function FormCategoryChart({ category, days }: CategoryChartProps) {
  const [period, setPeriod] = useState<ChartPeriod>(DEFAULT_PERIOD);
  const [mode, setMode] = useState<ChartMode>('perDay');
  const [hiddenKeys, setHiddenKeys] = useState<readonly string[]>([]);

  const series = useMemo(() => buildSeries(category.fields), [category.fields]);
  const data = useMemo(() => {
    const sliced = sliceByPeriod(
      buildChartData(days, category.id, category.fields),
      period
    );
    return mode === 'cumulative' ? cumulate(sliced) : sliced;
  }, [days, category.id, category.fields, period, mode]);

  const toggleSeries = (key: string) => {
    setHiddenKeys((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  if (series.length === 0) {
    return (
      <div className="text-center py-16 bg-card border border-white/5 rounded-3xl">
        <p className="text-text-secondary">
          No number or time fields to chart in this category
        </p>
      </div>
    );
  }

  const leftUnit = series.find((s) => s.axis === 'left')?.unit ?? '';
  const rightSeries = series.find((s) => s.axis === 'right');
  const seriesByKey = new Map<string, ChartSeries>(series.map((s) => [s.key, s]));

  return (
    <div className="bg-card border border-white/5 rounded-3xl p-6 space-y-5">
      <PeriodButtons period={period} onChange={setPeriod} />

      <div className="flex flex-wrap gap-2" role="group" aria-label="Chart mode">
        {CHART_MODES.map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            aria-pressed={m === mode}
            className={`px-4 py-2 rounded-full text-sm font-medium transition-all duration-200 border ${
              m === mode
                ? 'bg-lime text-background border-lime shadow-[0_0_18px_rgba(184,255,54,0.25)]'
                : 'bg-surface text-text-secondary border-white/10 hover:text-text-primary hover:bg-white/5'
            }`}
          >
            {MODE_LABELS[m]}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Series visibility">
        {series.map((s) => {
          const hidden = hiddenKeys.includes(s.key);
          return (
            <button
              key={s.key}
              onClick={() => toggleSeries(s.key)}
              aria-pressed={!hidden}
              className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm border transition-all duration-200 ${
                hidden
                  ? 'bg-surface text-text-disabled border-white/5 line-through'
                  : 'bg-surface text-text-primary border-white/10'
              }`}
            >
              <span
                aria-hidden="true"
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: hidden ? '#3a3a3a' : s.color }}
              />
              {s.name}
              <span className="text-text-disabled">{s.unit}</span>
            </button>
          );
        })}
      </div>

      <div style={{ height: CHART_HEIGHT_PX }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={GRID_COLOR} vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fill: AXIS_TICK_COLOR, fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: GRID_COLOR }}
              minTickGap={24}
            />
            <YAxis
              yAxisId="left"
              tick={{ fill: AXIS_TICK_COLOR, fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={44}
              label={{
                value: leftUnit,
                position: 'insideTopLeft',
                offset: -8,
                fill: AXIS_TICK_COLOR,
                fontSize: 12,
              }}
            />
            {rightSeries && (
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fill: AXIS_TICK_COLOR, fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                width={44}
                label={{
                  value: rightSeries.unit,
                  position: 'insideTopRight',
                  offset: -8,
                  fill: AXIS_TICK_COLOR,
                  fontSize: 12,
                }}
              />
            )}
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(value, name) => {
                const s = typeof name === 'string' ? seriesByKey.get(name) : undefined;
                const label = s?.name ?? name;
                const unit = s?.unit ?? '';
                return [`${value} ${unit}`.trim(), label];
              }}
              labelStyle={{ color: '#8a8a8a' }}
            />
            {series.map((s) => (
              <Line
                key={s.key}
                yAxisId={s.axis}
                type="monotone"
                dataKey={s.key}
                name={s.key}
                stroke={s.color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: '#1a1a1a' }}
                connectNulls
                hide={hiddenKeys.includes(s.key)}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
