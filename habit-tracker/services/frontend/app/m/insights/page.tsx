'use client';
// [review:need-review] PHASE-01/46-mobile-insights
// summary: mobile Insights screen — markup only, all list/view/run state comes from useInsights (shared with the desktop shell); single-column cards that expand to a Markdown-rendered report and a full-width "run analysis" button over the selected window; all body text stays text-sm or larger so it reads without a zoom

import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import Markdown from '@/components/Markdown';
import {
  formatReportDate,
  useInsights,
  INSIGHT_PERIOD_OPTIONS,
} from '@/hooks/useInsights';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

export default function MobileInsightsPage() {
  const {
    reports,
    loading,
    error,
    view,
    period,
    runState,
    setError,
    setPeriod,
    openReport,
    generate,
    dismissRun,
  } = useInsights();

  if (loading) return <LoadingSpinner size="lg" />;

  const running = runState.status === 'loading';

  return (
    <div className="space-y-5 animate-fade-rise">
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}
      {runState.status === 'error' && (
        <ErrorAlert message={runState.message} onDismiss={dismissRun} />
      )}

      <div className="bg-card border border-white/5 rounded-3xl p-4 space-y-4">
        <div>
          <span className="block text-sm font-medium text-text-secondary mb-3">
            Период разбора
          </span>
          <div className="flex gap-2">
            {INSIGHT_PERIOD_OPTIONS.map((option) => {
              const selected = period === option;
              return (
                <button
                  key={option}
                  type="button"
                  onClick={() => setPeriod(option)}
                  aria-pressed={selected}
                  disabled={running}
                  style={{ minHeight: TAP_TARGET_PX }}
                  className={`flex-1 rounded-2xl border text-sm font-medium transition-colors duration-200 disabled:opacity-50 ${
                    selected
                      ? 'border-lime bg-lime/10 text-lime'
                      : 'border-white/10 bg-surface text-text-secondary active:border-white/25'
                  }`}
                >
                  {option} дн.
                </button>
              );
            })}
          </div>
        </div>

        <button
          type="button"
          onClick={() => void generate()}
          disabled={running}
          style={{ minHeight: TAP_TARGET_PX }}
          className="w-full inline-flex items-center justify-center gap-2 bg-lime text-background rounded-2xl font-medium transition-transform duration-200 active:scale-95 disabled:opacity-50"
        >
          <Sparkles className="w-5 h-5" strokeWidth={2} />
          {running ? 'Запускаем разбор…' : 'Запустить разбор'}
        </button>
      </div>

      {reports.length === 0 ? (
        <div className="text-center py-12 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <Sparkles className="w-7 h-7 text-text-disabled" strokeWidth={2} />
          </div>
          <p className="text-sm text-text-secondary px-6">
            Пока нет ни одного отчёта — запустите первый разбор
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {reports.map((item) => {
            const isOpen = view.status === 'open' && view.id === item.id;
            const isLoading = view.status === 'loading' && view.id === item.id;
            const isError = view.status === 'error' && view.id === item.id;
            return (
              <div
                key={item.id}
                className="bg-card border border-white/5 rounded-3xl overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => void openReport(item.id)}
                  aria-expanded={isOpen}
                  style={{ minHeight: TAP_TARGET_PX }}
                  className="w-full text-left px-4 py-4 flex items-start justify-between gap-3"
                >
                  <div className="flex items-start gap-3 min-w-0">
                    <div className="p-2 rounded-2xl bg-lime/10 flex-shrink-0">
                      <Sparkles className="w-5 h-5 text-lime" strokeWidth={2} />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-text-primary">
                        Разбор за {item.period_days} дн.
                      </p>
                      <p className="text-sm text-text-secondary mt-0.5">
                        {formatReportDate(item.created_at)} · {item.model}
                      </p>
                      {!isOpen && (
                        <p className="text-sm text-text-disabled mt-2 line-clamp-2">
                          {item.preview}
                        </p>
                      )}
                    </div>
                  </div>
                  <span className="text-text-secondary flex-shrink-0">
                    {isOpen ? (
                      <ChevronUp className="w-5 h-5" strokeWidth={2} />
                    ) : (
                      <ChevronDown className="w-5 h-5" strokeWidth={2} />
                    )}
                  </span>
                </button>

                {isLoading && (
                  <div className="px-4 pb-4">
                    <LoadingSpinner size="sm" />
                  </div>
                )}
                {isError && (
                  <div className="px-4 pb-4">
                    <p className="text-sm text-danger">{view.message}</p>
                  </div>
                )}
                {isOpen && (
                  <div className="px-4 pb-5 border-t border-white/5 pt-4">
                    <Markdown content={view.report.content} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
