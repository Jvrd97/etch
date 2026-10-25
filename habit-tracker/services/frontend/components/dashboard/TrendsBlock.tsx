// [review:need-review] #78
// summary: shared desktop/mobile Trends block - up to four rows of icon, average with unit, sparkline and delta to the previous period, each linking to its category page; mobile adds the 7/30/90 selector

import Link from 'next/link';
import type { TrendState } from '@/hooks/useDashboard';
import { PERIOD_LABELS } from '@/lib/chart-data';
import { MOBILE_PATH_PREFIX } from '@/lib/routes';
import {
  TREND_PERIODS,
  chartPeriodFor,
  formatTrendAverage,
  formatTrendDeltaParts,
  type DashboardTrend,
  type TrendPeriod,
} from '@/lib/trends';
import { TAP_TARGET_PX } from '@/lib/ui-constants';
import { TrendSparkline } from './TrendSparkline';

interface TrendsBlockProps {
  state: TrendState;
  period: TrendPeriod;
  onPeriodChange: (period: TrendPeriod) => void;
  mobile?: boolean;
}

/**
 * Desktop opens `/categories/<id>`, whose chart starts on thirty days, the one
 * period the desktop block shows. Mobile also lets the reader pick 7 or 90, so
 * it carries the period for the chart to open on, which keeps the average on
 * the category page equal to the one in this row.
 */
function categoryHref(trend: DashboardTrend, period: TrendPeriod, mobile: boolean): string {
  return mobile
    ? `${MOBILE_PATH_PREFIX}/categories/${trend.categoryId}?period=${period}`
    : `/categories/${trend.categoryId}`;
}

interface TrendRowProps {
  trend: DashboardTrend;
  period: TrendPeriod;
  mobile: boolean;
}

function TrendRow({ trend, period, mobile }: TrendRowProps) {
  const { change, comparison } = formatTrendDeltaParts(trend.deltaPercent, period);
  return (
    <li>
      <Link
        href={categoryHref(trend, period, mobile)}
        style={mobile ? { minHeight: TAP_TARGET_PX } : undefined}
        className="flex items-center gap-3 rounded-2xl py-3 transition-colors duration-200 hover:bg-white/5"
      >
        <span
          aria-hidden="true"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-surface"
        >
          {trend.icon ?? (
            <span
              data-testid="trend-dot"
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: trend.color }}
            />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-text-primary">{trend.categoryName}</span>{' '}
          <span className="block truncate text-[13px] text-text-secondary">
            avg {formatTrendAverage(trend.average, trend.unit)}
          </span>
        </span>{' '}
        <TrendSparkline points={trend.sparkline} color={trend.color} />{' '}
        <span className="w-20 shrink-0 text-right">
          <span className="block text-sm font-semibold text-text-primary">{change}</span>{' '}
          <span className="block text-[12px] text-text-secondary">{comparison}</span>
        </span>
      </Link>
    </li>
  );
}

function PeriodSelector({
  period,
  onChange,
}: {
  period: TrendPeriod;
  onChange: (period: TrendPeriod) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Trends period"
      className="grid w-full grid-cols-3 gap-1 rounded-full border border-white/5 bg-surface p-0.5"
    >
      {TREND_PERIODS.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          aria-pressed={period === option}
          style={{ minHeight: TAP_TARGET_PX }}
          className={`rounded-full text-sm font-medium transition-colors duration-200 ${
            period === option ? 'bg-lime text-background' : 'text-text-secondary'
          }`}
        >
          {PERIOD_LABELS[chartPeriodFor(option)]}
        </button>
      ))}
    </div>
  );
}

export function TrendsBlock({ state, period, onPeriodChange, mobile = false }: TrendsBlockProps) {
  const gutter = mobile ? 'px-4' : 'px-6';
  return (
    <section
      aria-labelledby="trends-title"
      className="overflow-hidden rounded-3xl border border-white/5 bg-card"
    >
      <div
        className={`${gutter} flex flex-wrap items-center justify-between gap-3 border-b border-white/5 py-5`}
      >
        <div>
          <h2 id="trends-title" className="text-[22px] font-semibold text-text-primary">
            Trends
          </h2>
          <p className="text-[13px] text-text-secondary">
            Daily average, last {period} days
          </p>
        </div>
        {mobile && <PeriodSelector period={period} onChange={onPeriodChange} />}
      </div>
      <div className={`${gutter} py-2`}>
        {state.status === 'loading' && (
          <p role="status" className="py-6 text-sm text-text-secondary">
            Loading trends…
          </p>
        )}
        {state.status === 'error' && (
          <p role="alert" className="py-6 text-sm text-danger">
            {state.message}
          </p>
        )}
        {state.status === 'ready' && state.trends.length === 0 && (
          <p className="py-6 text-sm text-text-secondary">
            No numeric entries in the last {period} days yet.
          </p>
        )}
        {state.status === 'ready' && state.trends.length > 0 && (
          <ul>
            {state.trends.map((trend) => (
              <TrendRow key={trend.categoryId} trend={trend} period={period} mobile={mobile} />
            ))}
          </ul>
        )}
        {mobile && state.status === 'ready' && state.trends.length > 0 && (
          <p className="pb-3 pt-1 text-[13px] text-text-secondary">Tap a habit for details</p>
        )}
      </div>
    </section>
  );
}
