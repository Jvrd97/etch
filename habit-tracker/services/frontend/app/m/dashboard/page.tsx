'use client';
// [review:need-review] PHASE-01/73-dashboard-hero-today-ring, PHASE-03/123
// summary: mobile Dashboard at /m/dashboard — hero card shows today's ring, the last written entry with its time of writing and the tip of the day, in the same wording as the desktop shell; moved off the bare /m in #123, which became the redirect into Today

import { useDashboard, INSIGHT_PERIOD_OPTIONS } from '@/hooks/useDashboard';
import ProgressRing from '@/components/ProgressRing';
import Markdown from '@/components/Markdown';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import { ENTRIES_TODAY_LABEL, heroLastEntryLine, TAP_TARGET_PX } from '@/lib/ui-constants';
import { NEW_ENTRY_QUERY } from '@/lib/routes';
import {
  ArrowRight,
  BarChart3,
  BookText,
  Calendar,
  FolderPlus,
  PenLine,
  Plus,
  RotateCcw,
  Sparkles,
} from 'lucide-react';
import Link from 'next/link';

const MOBILE_RING_SIZE_PX = 128;

export default function MobileDashboardPage() {
  const {
    stats,
    hero,
    loading,
    error,
    insight,
    insightPeriod,
    setError,
    setInsightPeriod,
    generateInsight,
  } = useDashboard();

  if (loading) return <LoadingSpinner size="lg" />;
  if (error) return <ErrorAlert message={error} onDismiss={() => setError(null)} />;

  const kpis = [
    { label: 'Categories', value: stats.categoriesCount, href: '/categories', icon: BarChart3 },
    { label: 'Entries', value: stats.entriesCount, href: '/entries', icon: Calendar },
    { label: 'Journal', value: stats.journalCount, href: '/journal', icon: BookText },
  ];

  const quickActions = [
    { label: 'Add category', href: '/categories?action=new', icon: FolderPlus },
    { label: 'Log entry', href: `/entries${NEW_ENTRY_QUERY}`, icon: Plus },
    { label: 'Write journal', href: '/journal?action=new', icon: PenLine },
  ];

  return (
    <div className="space-y-6 animate-fade-rise">
      {/* Hero score card */}
      <div className="bg-card border border-white/5 rounded-3xl p-6 flex flex-col items-center gap-5 text-center">
        <div className="relative flex-shrink-0">
          <ProgressRing progress={hero.ringProgress} size={MOBILE_RING_SIZE_PX} />
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-3xl font-bold text-text-primary leading-none">
              {hero.entriesToday}
            </span>
            <span className="text-[12px] font-medium text-text-secondary mt-1">
              {ENTRIES_TODAY_LABEL}
            </span>
          </div>
        </div>
        <div>
          <p className="text-base font-semibold text-text-primary">
            {heroLastEntryLine(hero.lastEntry)}
          </p>
          {hero.lastEntry !== null && (
            <p className="text-[12px] text-text-disabled mt-1">{hero.lastEntry.loggedAgo}</p>
          )}
          <p className="text-text-secondary mt-2 text-sm px-2">{hero.tip.text}</p>
        </div>
        <Link
          href={`/entries${NEW_ENTRY_QUERY}`}
          style={{ minHeight: TAP_TARGET_PX }}
          className="inline-flex items-center justify-center gap-2 w-full px-6 py-3 bg-lime text-background rounded-2xl font-medium transition-colors duration-200"
        >
          <Plus className="w-4 h-4" strokeWidth={2} />
          Log entry
        </Link>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-3 gap-3">
        {kpis.map(({ label, value, href, icon: Icon }) => (
          <Link
            key={label}
            href={href}
            className="bg-card border border-white/5 rounded-2xl p-4 flex flex-col gap-2"
          >
            <div className="p-2 rounded-xl bg-lime/10 w-fit">
              <Icon className="w-4 h-4 text-lime" strokeWidth={2} />
            </div>
            <div className="min-w-0">
              <p className="text-2xl font-bold text-text-primary leading-none">{value}</p>
              <p className="text-[11px] font-medium text-text-secondary mt-1 truncate">{label}</p>
            </div>
          </Link>
        ))}
      </div>

      {/* AI insights */}
      <section className="bg-card border border-white/5 rounded-3xl overflow-hidden">
        <div className="px-4 py-4 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-lime/10">
              <Sparkles className="w-5 h-5 text-lime" strokeWidth={2} />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-text-primary">AI-разбор</h2>
              <p className="text-[12px] text-text-secondary">
                Тренды и корреляции за последние {insightPeriod} дней
              </p>
            </div>
          </div>
          <div
            role="group"
            aria-label="Период разбора"
            className="mt-4 grid grid-cols-3 gap-1 rounded-full bg-surface border border-white/5 p-1"
          >
            {INSIGHT_PERIOD_OPTIONS.map((days) => (
              <button
                key={days}
                type="button"
                onClick={() => setInsightPeriod(days)}
                disabled={insight.status === 'loading'}
                aria-pressed={insightPeriod === days}
                className={`py-2 rounded-full text-sm font-medium transition-colors duration-200 disabled:opacity-50 ${
                  insightPeriod === days
                    ? 'bg-lime text-background'
                    : 'text-text-secondary'
                }`}
              >
                {days} дн.
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={generateInsight}
            disabled={insight.status === 'loading'}
            style={{ minHeight: TAP_TARGET_PX }}
            className="mt-3 inline-flex items-center justify-center gap-2 w-full px-6 py-3 bg-lime text-background rounded-2xl font-medium transition-colors duration-200 disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4" strokeWidth={2} />
            Разбор периода
          </button>
        </div>
        <div className="px-4 py-4">
          {insight.status === 'idle' && (
            <p className="text-text-secondary text-sm">
              Нажмите «Разбор периода», чтобы получить AI-отчёт по вашим данным.
            </p>
          )}
          {insight.status === 'loading' && (
            <div className="flex items-center gap-3 py-4" role="status" aria-live="polite">
              <span className="relative flex h-3.5 w-3.5 flex-shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-lime opacity-60" />
                <span className="relative inline-flex rounded-full h-3.5 w-3.5 bg-lime" />
              </span>
              <p className="text-text-secondary text-sm">Анализирую период…</p>
            </div>
          )}
          {insight.status === 'error' && (
            <div className="space-y-3 py-1">
              <p className="text-red-400 text-sm">{insight.message}</p>
              <button
                type="button"
                onClick={generateInsight}
                className="inline-flex items-center gap-2 px-5 py-2.5 border border-lime/40 text-lime rounded-2xl font-medium transition-colors duration-200"
              >
                <RotateCcw className="w-4 h-4" strokeWidth={2} />
                Retry
              </button>
            </div>
          )}
          {insight.status === 'ready' && (
            <div>
              <Markdown content={insight.report.content} />
              <p className="mt-4 text-[12px] text-text-disabled">
                Период: {insight.report.period_days} дн. · Модель: {insight.report.model}
              </p>
            </div>
          )}
        </div>
      </section>

      {/* Recent activity */}
      <section className="bg-card border border-white/5 rounded-3xl overflow-hidden">
        <div className="px-4 py-4 border-b border-white/5 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-text-primary">Recent activity</h2>
          <Link
            href="/entries"
            className="text-sm font-medium text-text-secondary inline-flex items-center gap-1"
          >
            View all
            <ArrowRight className="w-4 h-4" strokeWidth={2} />
          </Link>
        </div>
        <div className="px-4 py-2">
          {stats.recentEntries.length === 0 ? (
            <div className="text-center py-10">
              <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
                <Calendar className="w-7 h-7 text-text-disabled" strokeWidth={2} />
              </div>
              <p className="text-text-secondary text-sm">Nothing here yet</p>
              <Link
                href={`/entries${NEW_ENTRY_QUERY}`}
                style={{ minHeight: TAP_TARGET_PX }}
                className="mt-4 inline-flex items-center justify-center gap-2 px-6 py-3 bg-lime text-background rounded-2xl font-medium"
              >
                Create first entry
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-white/5">
              {stats.recentEntries.map((entry) => (
                <Link
                  key={entry.id}
                  href={`/entries/${entry.id}`}
                  style={{ minHeight: TAP_TARGET_PX }}
                  className="flex items-center justify-between gap-3 py-3"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="p-2 rounded-xl bg-surface flex-shrink-0">
                      <Calendar className="w-4 h-4 text-lime" strokeWidth={2} />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-text-primary truncate">
                        Entry #{entry.id}
                      </p>
                      <p className="text-[12px] text-text-secondary mt-0.5">{entry.entry_date}</p>
                    </div>
                  </div>
                  <span className="text-[12px] text-text-disabled flex-shrink-0">
                    {entry.values.length} values
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Quick actions */}
      <section className="space-y-3">
        {quickActions.map(({ label, href, icon: Icon }) => (
          <Link
            key={label}
            href={href}
            style={{ minHeight: TAP_TARGET_PX }}
            className="bg-surface border border-white/5 rounded-2xl p-4 flex items-center gap-4 transition-colors duration-200"
          >
            <div className="p-2.5 rounded-xl bg-lime text-background">
              <Icon className="w-5 h-5" strokeWidth={2} />
            </div>
            <span className="text-base font-medium text-text-primary">{label}</span>
          </Link>
        ))}
      </section>
    </div>
  );
}
