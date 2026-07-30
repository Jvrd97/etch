'use client';
// [review:need-review] PHASE-01/74-daily-summary-journal
// summary: mobile day-summary screen — same useDailySummary flow as the desktop page (metrics + the day's journal text), laid out for a 375pt screen: every control on its own 44pt row, one card per operation

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
import { MOBILE_PATH_PREFIX } from '@/lib/routes';
import { TAP_TARGET_PX, entryInputClass } from '@/lib/ui-constants';

const PRIMARY_BUTTON_CLASS =
  'w-full inline-flex items-center justify-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-transform duration-200 active:scale-95 disabled:opacity-40 disabled:active:scale-100';

const SECONDARY_BUTTON_CLASS =
  'w-full inline-flex items-center justify-center px-5 py-3 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-transform duration-200 active:scale-95';

interface MetricCardProps {
  metric: LogMetricOp;
  /** Where the metric lands, named — the ids alone are not reviewable. */
  label: MetricLabel;
  checked: boolean;
  onToggle: (enabled: boolean) => void;
}

/**
 * One planned metric as a card.
 *
 * The desktop row puts the checkbox, the wording and the destination on one
 * line; at 375pt that line wraps into mush. Here the checkbox owns a full-width
 * 44pt row and everything else stacks under it, in the same order.
 */
function MetricCard({ metric, label, checked, onToggle }: MetricCardProps) {
  return (
    <div className="bg-card border border-white/5 rounded-3xl p-4 space-y-2">
      <label
        style={{ minHeight: TAP_TARGET_PX }}
        className="flex items-center gap-3 cursor-pointer"
      >
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onToggle(e.target.checked)}
          aria-label={metricCheckboxLabel(metric)}
          className="w-5 h-5 accent-lime rounded shrink-0"
        />
        <span className="min-w-0 text-sm font-medium text-text-primary break-words">
          {metric.source_text}
        </span>
      </label>

      <p className="text-[13px] text-text-disabled break-words">
        {metric.value} · {label.categoryName} · {label.fieldName}
      </p>

      {(metric.uncertain || metric.implausible) && (
        <p className="text-[13px] text-danger break-words">
          {metric.implausible
            ? 'число выглядит неправдоподобно — проверьте перед записью'
            : 'модель не уверена, куда это относится'}
        </p>
      )}
    </div>
  );
}

/** What the model heard but could not place; inert, as on the desktop screen. */
function UnresolvedSection({ items }: { items: UnresolvedMetric[] }) {
  if (items.length === 0) return null;
  return (
    <div className="bg-card border border-white/5 rounded-3xl p-4">
      <p className="flex items-center gap-2 text-sm font-semibold text-text-secondary">
        <HelpCircle className="w-4 h-4 shrink-0" strokeWidth={2} />
        {UNRESOLVED_TITLE}
      </p>
      <ul aria-label={UNRESOLVED_TITLE} className="mt-3 space-y-2">
        {items.map((item, i) => (
          <li key={i} className="text-[13px] text-text-secondary break-words">
            {item.text}
            {item.reason && <span className="text-text-disabled"> · {item.reason}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface JournalCardProps {
  journal: JournalOp;
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  replace: boolean;
  onToggleReplace: (replace: boolean) => void;
  canReplace: boolean;
}

/**
 * The day's text as a card: what will happen to it, then the text itself.
 *
 * Same two controls as the desktop section, each on its own tap row, and the
 * generated text is clamped: at 375pt a full day of Markdown would push the
 * write button off the screen, and the point of the preview is the decision
 * above it, not proofreading.
 */
function JournalCard({
  journal,
  enabled,
  onToggle,
  replace,
  onToggleReplace,
  canReplace,
}: JournalCardProps) {
  return (
    <div className="bg-card border border-white/5 rounded-3xl p-4 space-y-2">
      <label
        style={{ minHeight: TAP_TARGET_PX }}
        className="flex items-center gap-3 cursor-pointer"
      >
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onToggle(e.target.checked)}
          aria-label={journalCheckboxLabel(journal)}
          className="w-5 h-5 accent-lime rounded shrink-0"
        />
        <span className="min-w-0 text-sm font-medium text-text-primary">
          {journalCheckboxLabel(journal)}
        </span>
      </label>

      <p className="text-[13px] text-text-disabled break-words">
        {journal.mode === 'create'
          ? 'За эту дату записи ещё нет — текст дня станет новой записью.'
          : 'Текст допишется в конец записи, ничего не пропадёт.'}
      </p>

      <p className="text-[13px] text-text-secondary whitespace-pre-wrap break-words line-clamp-6">
        {journal.content}
      </p>

      {canReplace && (
        <label
          style={{ minHeight: TAP_TARGET_PX }}
          className="flex items-center gap-3 cursor-pointer"
        >
          <input
            type="checkbox"
            checked={replace}
            onChange={(e) => onToggleReplace(e.target.checked)}
            aria-label={JOURNAL_REPLACE_LABEL}
            className="w-5 h-5 accent-danger rounded shrink-0"
          />
          <span className="min-w-0 text-[13px] text-text-secondary break-words">
            {JOURNAL_REPLACE_LABEL} — старая запись будет перезаписана
          </span>
        </label>
      )}
    </div>
  );
}

export default function MobileDailySummaryPage() {
  const router = useRouter();
  const day = useDailySummary({
    onApplied: () => router.push(`${MOBILE_PATH_PREFIX}/entries`),
  });
  const generate = () => void day.generate();

  return (
    <div className="space-y-4 animate-fade-rise">
      <p className="text-sm text-text-secondary">
        Расскажите, как прошёл день — получите план записей и запишите выбранное одним
        нажатием.
      </p>

      <input
        type="date"
        value={day.entryDate}
        onChange={(e) => day.setEntryDate(e.target.value)}
        aria-label="Дата дня"
        style={{ minHeight: TAP_TARGET_PX }}
        className={entryInputClass}
      />

      <textarea
        value={day.transcript}
        onChange={(e) => day.setTranscript(e.target.value)}
        rows={6}
        aria-label="Как прошёл день"
        placeholder="Например: отжался 30 раз, пробежал 5 километров"
        className={`${entryInputClass} resize-y`}
      />

      <button
        type="button"
        onClick={generate}
        disabled={!day.canGenerate}
        style={{ minHeight: TAP_TARGET_PX }}
        className={PRIMARY_BUTTON_CLASS}
      >
        <Sparkles className="w-4 h-4" strokeWidth={2} />
        Разобрать день
      </button>

      {day.draft.status === 'loading' && <LoadingSpinner size="lg" />}

      {day.draft.status === 'error' && (
        <div className="space-y-3">
          <ErrorAlert message={day.draft.message} />
          <button
            type="button"
            onClick={generate}
            style={{ minHeight: TAP_TARGET_PX }}
            className={SECONDARY_BUTTON_CLASS}
          >
            Retry
          </button>
        </div>
      )}

      {day.draft.status === 'done' &&
        (day.draft.plan.metrics.length === 0 &&
        day.unresolved.length === 0 &&
        day.journal === null ? (
          <p className="text-sm text-text-secondary">
            Модель не нашла в тексте чисел для записи. Попробуйте рассказать подробнее.
          </p>
        ) : (
          <div className="space-y-3">
            {day.draft.plan.metrics.map((metric, i) => (
              <MetricCard
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
              <JournalCard
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
                style={{ minHeight: TAP_TARGET_PX }}
                className={PRIMARY_BUTTON_CLASS}
              >
                {day.applyState.status === 'applying'
                  ? 'Записываем…'
                  : `Записать выбранное (${day.enabledCount})`}
              </button>
            )}
          </div>
        ))}
    </div>
  );
}
