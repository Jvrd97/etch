'use client';
// [review:need-review] PHASE-01/74-daily-summary-journal
// summary: desktop day-summary screen — markup only; the text/date/plan/journal/apply flow lives in useDailySummary, which /m/daily-summary renders with its own layout

import { useRouter } from 'next/navigation';
import { HelpCircle, Sparkles } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import {
  JOURNAL_REPLACE_LABEL,
  UNRESOLVED_TITLE,
  journalCheckboxLabel,
  metricCheckboxLabel,
  useDailySummary,
  type MetricLabel,
} from '@/hooks/useDailySummary';
import type { JournalOp, LogMetricOp, UnresolvedMetric } from '@/lib/api';

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

interface JournalSectionProps {
  journal: JournalOp;
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  replace: boolean;
  onToggleReplace: (replace: boolean) => void;
  canReplace: boolean;
}

/**
 * The day's text, with the collision stated rather than implied.
 *
 * The heading says which of the two things will happen — append or create — so
 * the checkbox is an approval of a known outcome. Replacement sits next to it,
 * unchecked, and is named a replacement: "обновить" would read as harmless and
 * this is the one control on the screen that deletes what the user wrote.
 */
function JournalSection({
  journal,
  enabled,
  onToggle,
  replace,
  onToggleReplace,
  canReplace,
}: JournalSectionProps) {
  return (
    <div className="bg-card border border-white/5 rounded-3xl px-6 py-5 space-y-3">
      <label className="flex items-start gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.target.checked)}
          aria-label={journalCheckboxLabel(journal)}
          className="mt-1.5 h-4 w-4 accent-lime shrink-0"
        />
        <div className="flex-1 min-w-0">
          <p className="text-base font-semibold text-text-primary">
            {journalCheckboxLabel(journal)}
          </p>
          <p className="text-[13px] text-text-disabled mt-1">
            {journal.mode === 'create'
              ? 'За эту дату записи ещё нет — текст дня станет новой записью.'
              : 'Текст дня допишется в конец существующей записи, ничего не пропадёт.'}
          </p>
          <p className="text-sm text-text-secondary mt-3 whitespace-pre-wrap break-words">
            {journal.content}
          </p>
        </div>
      </label>

      {canReplace && (
        <label className="flex items-center gap-3 cursor-pointer pl-7">
          <input
            type="checkbox"
            checked={replace}
            onChange={(e) => onToggleReplace(e.target.checked)}
            aria-label={JOURNAL_REPLACE_LABEL}
            className="h-4 w-4 accent-danger shrink-0"
          />
          <span className="text-[13px] text-text-secondary">
            {JOURNAL_REPLACE_LABEL} — старая запись за эту дату будет перезаписана
          </span>
        </label>
      )}
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
          {day.draft.plan.metrics.length === 0 &&
          day.unresolved.length === 0 &&
          day.journal === null ? (
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

              {day.journal !== null && (
                <JournalSection
                  journal={day.journal}
                  enabled={day.journalEnabled}
                  onToggle={day.setJournalEnabled}
                  replace={day.journalReplace}
                  onToggleReplace={day.setJournalReplace}
                  canReplace={day.canReplaceJournal}
                />
              )}

              <UnresolvedSection items={day.unresolved} />

              {day.applyState.status === 'error' && (
                <ErrorAlert message={day.applyState.message} />
              )}

              {(day.draft.plan.metrics.length > 0 || day.journal !== null) && (
                <button
                  type="button"
                  onClick={() => void day.apply()}
                  disabled={day.applyState.status === 'applying' || !day.canApply}
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
