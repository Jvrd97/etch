'use client';
// [review:need-review] PHASE-01/73-daily-summary-metrics-vertical
// summary: desktop day-summary screen — markup only; the text/date/plan/apply flow lives in useDailySummary, which /m/daily-summary renders with its own layout

import { useRouter } from 'next/navigation';
import { HelpCircle, Sparkles } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import {
  UNRESOLVED_TITLE,
  metricCheckboxLabel,
  useDailySummary,
  type MetricLabel,
} from '@/hooks/useDailySummary';
import type { LogMetricOp, UnresolvedMetric } from '@/lib/api';

function MetricRow({
  metric,
  label,
  checked,
  onToggle,
}: {
  metric: LogMetricOp;
  /** Where the metric lands, named — the ids alone are not reviewable. */
  label: MetricLabel;
  checked: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  return (
    <div className="bg-card border border-white/5 rounded-3xl px-6 py-5">
      <label className="flex items-start gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onToggle(e.target.checked)}
          aria-label={metricCheckboxLabel(metric)}
          className="mt-1.5 h-4 w-4 accent-lime shrink-0"
        />
        <div className="flex-1 min-w-0">
          <p className="text-base font-semibold text-text-primary break-words">
            {metric.source_text}
          </p>
          <p className="text-[13px] text-text-disabled mt-1">
            {metric.value} · {label.categoryName} · {label.fieldName}
          </p>
          {(metric.uncertain || metric.implausible) && (
            <p className="text-[13px] text-danger mt-1">
              {metric.implausible
                ? 'число выглядит неправдоподобно — проверьте перед записью'
                : 'модель не уверена, куда это относится'}
            </p>
          )}
        </div>
      </label>
    </div>
  );
}

/**
 * What the model heard but could not place, shown without checkboxes.
 *
 * Deliberately inert: creating a category from here would put "record my day"
 * and "change my schema" under one button, and those two mistakes cost very
 * different amounts. The constructor at /onboarding is where schema changes live.
 */
function UnresolvedSection({ items }: { items: UnresolvedMetric[] }) {
  if (items.length === 0) return null;
  return (
    <div className="bg-card border border-white/5 rounded-3xl px-6 py-5">
      <p className="flex items-center gap-2 text-sm font-semibold text-text-secondary">
        <HelpCircle className="w-4 h-4" strokeWidth={2} />
        {UNRESOLVED_TITLE}
      </p>
      <ul aria-label={UNRESOLVED_TITLE} className="mt-3 space-y-2">
        {items.map((item, i) => (
          <li key={i} className="text-sm text-text-secondary break-words">
            {item.text}
            {item.reason && <span className="text-text-disabled"> · {item.reason}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function DailySummaryPage() {
  const router = useRouter();
  const day = useDailySummary({ onApplied: () => router.push('/entries') });
  const generate = () => void day.generate();

  return (
    <div className="space-y-8 animate-fade-rise">
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          Разбор дня
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">
          Расскажите, как прошёл день — получите план записей и запишите выбранное
          одним нажатием.
        </p>
      </div>

      <div className="space-y-4">
        <label className="block">
          <span className="text-sm text-text-secondary">Дата</span>
          <input
            type="date"
            value={day.entryDate}
            onChange={(e) => day.setEntryDate(e.target.value)}
            aria-label="Дата дня"
            className="mt-1 block bg-card border border-white/5 rounded-2xl px-4 py-2.5 text-text-primary focus:outline-none focus:border-lime/30"
          />
        </label>

        <textarea
          value={day.transcript}
          onChange={(e) => day.setTranscript(e.target.value)}
          rows={8}
          aria-label="Как прошёл день"
          placeholder="Например: отжался 30 раз, пробежал 5 километров, выпил два литра воды"
          className="w-full bg-card border border-white/5 rounded-3xl px-5 py-4 text-text-primary placeholder:text-text-disabled focus:outline-none focus:border-lime/30 resize-y"
        />

        <button
          type="button"
          onClick={generate}
          disabled={!day.canGenerate}
          className="inline-flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
        >
          <Sparkles className="w-4 h-4" strokeWidth={2} />
          Разобрать день
        </button>
      </div>

      {day.draft.status === 'loading' && <LoadingSpinner size="lg" />}

      {day.draft.status === 'error' && (
        <div className="space-y-4">
          <ErrorAlert message={day.draft.message} />
          <button
            type="button"
            onClick={generate}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-colors duration-200 hover:border-lime/30"
          >
            Retry
          </button>
        </div>
      )}

      {day.draft.status === 'done' && (
        <div className="space-y-5">
          {day.draft.plan.metrics.length === 0 && day.unresolved.length === 0 ? (
            <p className="text-text-secondary">
              Модель не нашла в тексте чисел для записи. Попробуйте рассказать
              подробнее.
            </p>
          ) : (
            <>
              {day.draft.plan.metrics.map((metric, i) => (
                <MetricRow
                  // Index-keyed: a plan metric has no id, and the list is replaced
                  // wholesale by the next draft rather than reordered.
                  key={i}
                  metric={metric}
                  label={day.resolveLabel(metric)}
                  checked={day.metricStates[i]?.enabled ?? false}
                  onToggle={(enabled) => day.toggleMetric(i, enabled)}
                />
              ))}

              <UnresolvedSection items={day.unresolved} />

              {day.applyState.status === 'error' && (
                <ErrorAlert message={day.applyState.message} />
              )}

              {day.draft.plan.metrics.length > 0 && (
                <button
                  type="button"
                  onClick={() => void day.apply()}
                  disabled={
                    day.applyState.status === 'applying' || day.enabledCount === 0
                  }
                  className="inline-flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
                >
                  {day.applyState.status === 'applying'
                    ? 'Записываем…'
                    : `Записать выбранное (${day.enabledCount})`}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
