'use client';
// [review:need-review] PHASE-01/84-voice-day-input
// summary: the reviewable half of a parsed day, laid out for a 375pt screen — one card per planned metric (an estimated one saying so), the ticks, the day's text with its append/replace choice, and what could not be placed; shared by /m/daily-summary and the voice sheet on /m/today

import { CheckSquare, HelpCircle } from 'lucide-react';
import {
  CHECKLIST_TITLE,
  ESTIMATED_NOTE,
  JOURNAL_REPLACE_LABEL,
  UNRESOLVED_TITLE,
  checkCheckboxLabel,
  journalCheckboxLabel,
  metricCheckboxLabel,
  type MetricLabel,
  type UseDailySummaryResult,
} from '@/hooks/useDailySummary';
import type { CheckOp, JournalOp, LogMetricOp, UnresolvedMetric } from '@/lib/api';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

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

      {/* Not styled as the danger the two flags below are: an estimate is a
          normal outcome of describing a meal, and colouring it red would say
          something went wrong when nothing did. */}
      {metric.estimated && (
        <p className="text-[13px] text-text-secondary break-words">{ESTIMATED_NOTE}</p>
      )}

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

interface ChecklistCardProps {
  items: CheckOp[];
  states: { enabled: boolean }[];
  labels: MetricLabel[];
  onToggle: (index: number, enabled: boolean) => void;
}

/**
 * The boxes the retelling would tick, one 44pt tap row each.
 *
 * Same section as on the desktop screen and for the same reason — a tick edits
 * the day-map that Today edits, not a record of its own — but the destination
 * moves under the label instead of beside it, so nothing wraps at 375pt.
 */
function ChecklistCard({ items, states, labels, onToggle }: ChecklistCardProps) {
  if (items.length === 0) return null;
  return (
    <div className="bg-card border border-white/5 rounded-3xl p-4">
      <p className="flex items-center gap-2 text-sm font-semibold text-text-secondary">
        <CheckSquare className="w-4 h-4 shrink-0" strokeWidth={2} />
        {CHECKLIST_TITLE}
      </p>
      <ul aria-label={CHECKLIST_TITLE} className="mt-2 space-y-2">
        {items.map((check, i) => (
          // Index-keyed: a plan op has no id, and the whole list is replaced by
          // the next draft rather than reordered.
          <li key={i}>
            <label
              style={{ minHeight: TAP_TARGET_PX }}
              className="flex items-center gap-3 cursor-pointer"
            >
              <input
                type="checkbox"
                checked={states[i]?.enabled ?? false}
                onChange={(e) => onToggle(i, e.target.checked)}
                aria-label={checkCheckboxLabel(check)}
                className="w-5 h-5 accent-lime rounded shrink-0"
              />
              <span className="min-w-0 text-sm font-medium text-text-primary break-words">
                {check.source_text}
              </span>
            </label>
            <p className="text-[13px] text-text-disabled break-words">
              {labels[i].categoryName} · {labels[i].fieldName}
            </p>
            {check.uncertain && (
              <p className="text-[13px] text-danger break-words">
                модель не уверена, что речь про эту галочку
              </p>
            )}
          </li>
        ))}
      </ul>
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

/**
 * Everything a parsed day proposes, as cards the user can uncheck.
 *
 * Takes the whole `useDailySummary` result rather than a dozen props: the
 * sections are already one flow — a metric, a tick and the day's text are three
 * halves of one apply — and the two screens that render this differ only in
 * where they put the button that ends it. The page keeps its button in the
 * content column; the sheet puts it in the bar. Everything above it is here.
 */
export default function DayPlanPreview({ day }: { day: UseDailySummaryResult }) {
  if (day.draft.status !== 'done') return null;
  return (
    <>
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

      <ChecklistCard
        items={day.checklist}
        states={day.checkStates}
        labels={day.checklist.map(day.resolveLabel)}
        onToggle={day.toggleCheck}
      />

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
    </>
  );
}

/**
 * Whether a finished draft proposes nothing at all.
 *
 * Both screens answer that with the same sentence — "расскажите подробнее" —
 * and both have to ask it of the same four lists, so the question lives beside
 * the component that would otherwise render an empty space instead.
 */
export function planIsEmpty(day: UseDailySummaryResult): boolean {
  if (day.draft.status !== 'done') return false;
  return (
    day.draft.plan.metrics.length === 0 &&
    day.checklist.length === 0 &&
    day.unresolved.length === 0 &&
    day.journal === null
  );
}

/** Whether a finished draft has anything the apply button could write. */
export function planHasWrites(day: UseDailySummaryResult): boolean {
  if (day.draft.status !== 'done') return false;
  return (
    day.draft.plan.metrics.length > 0 || day.checklist.length > 0 || day.journal !== null
  );
}

/** Shown in place of the cards when the model found nothing to write. */
export const EMPTY_PLAN_MESSAGE =
  'Модель не нашла в тексте чисел для записи. Попробуйте рассказать подробнее.';
