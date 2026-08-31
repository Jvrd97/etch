'use client';
// [review:need-review] PHASE-03/115, PHASE-03/187
// summary: the card under an assistant message — a checkbox per proposed operation, «применить» and «отклонить», and after the apply the count of what was written; the second tap is blocked by the card rather than left to the idempotency key alone
// summary: PHASE-03/187 gives the day plan a row of its own — one tick for the whole day, wording that separates filling an empty day from replacing a full one, and the codes by which a replacement keeps the marks of the lines it kept

import { useMemo, useState } from 'react';
import { Check, X } from 'lucide-react';
import type {
  ChatPlan,
  ChatPlanCheckOp,
  ChatPlanDayPlanOp,
  ChatPlanMetricOp,
  ChatPlanSelection,
} from '@/lib/api';

interface ChatPlanCardProps {
  plan: ChatPlan;
  /** Applies what is still ticked; resolves with the plan as it now stands. */
  onApply: (planId: number, selection: ChatPlanSelection) => Promise<void>;
  onDismiss: (planId: number) => Promise<void>;
}

/** A row of the card: one proposed operation with the wording it was read from. */
interface Row {
  key: string;
  label: string;
  /** Unticked on arrival when the model itself was unsure. */
  initiallyChecked: boolean;
}

function metricRows(metrics: ChatPlanMetricOp[]): Row[] {
  return metrics.map((op, index) => ({
    key: `metric-${index}`,
    label: `${op.source_text} — ${op.value}`,
    initiallyChecked: !op.uncertain && !op.suspicious,
  }));
}

function checkRows(checklist: ChatPlanCheckOp[]): Row[] {
  return checklist.map((op, index) => ({
    key: `check-${index}`,
    label: op.source_text,
    initiallyChecked: !op.uncertain,
  }));
}

/** Every line of a proposed day plan, sections flattened away. */
function dayPlanItems(dayPlan: ChatPlanDayPlanOp) {
  return dayPlan.sections.flatMap((section) => section.items);
}

/** «2 строки» — the count a person reads, not `2 строк(и)`. */
function lineCount(count: number): string {
  const tail = count % 100;
  if (tail > 10 && tail < 20) return `${count} строк`;
  const last = count % 10;
  if (last === 1) return `${count} строка`;
  if (last >= 2 && last <= 4) return `${count} строки`;
  return `${count} строк`;
}

/**
 * Плашка предложения под ответом чата.
 *
 * Плашка не «отправляет план» — она отправляет то, что человек оставил
 * отмеченным. Сервер сверит присланное с сохранённым планом и откажет на всём,
 * чего в нём не было, поэтому здесь можно только снимать галочки, но не
 * добавлять строки.
 *
 * План дня — одна галочка на весь день, а не галочка на строку: он пишется
 * целиком или никак, и «применено 14 строк из 20» было бы обещанием, которого
 * выполнить нельзя. Перезапись названа перезаписью и говорит, что именно
 * уцелеет: отметки держатся за коды строк, поэтому коды и напечатаны рядом.
 * Имя операции ставит сервер по состоянию дня, а не модель, — экран его только
 * читает.
 *
 * После применения плашка показывает, что именно записано, и второй раз вслепую
 * нажать не даёт. Ключ идемпотентности на сервере всё равно страхует, но кнопка,
 * которая выглядит рабочей и ничего не делает, — это отдельная неправда экрана.
 */
export default function ChatPlanCard({ plan, onApply, onDismiss }: ChatPlanCardProps) {
  const rows = useMemo(
    () => [...metricRows(plan.plan.metrics), ...checkRows(plan.plan.checklist)],
    [plan],
  );
  const [ticked, setTicked] = useState<Set<string>>(
    () => new Set(rows.filter((row) => row.initiallyChecked).map((row) => row.key)),
  );
  const [journalTicked, setJournalTicked] = useState(plan.plan.journal !== null);
  const dayPlan = plan.plan.day_plan;
  const [dayPlanTicked, setDayPlanTicked] = useState(dayPlan !== null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const settled = plan.status !== 'proposed';
  const chosenCount =
    ticked.size +
    (plan.plan.journal && journalTicked ? 1 : 0) +
    (dayPlan && dayPlanTicked ? 1 : 0);

  const toggle = (key: string) => {
    setTicked((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const apply = async () => {
    if (busy || settled || chosenCount === 0) return;
    setBusy(true);
    setError(null);
    try {
      await onApply(plan.id, {
        metrics: plan.plan.metrics.filter((_, index) => ticked.has(`metric-${index}`)),
        checklist: plan.plan.checklist.filter((_, index) =>
          ticked.has(`check-${index}`),
        ),
        journal: journalTicked ? plan.plan.journal : null,
        day_plan: Boolean(dayPlan) && dayPlanTicked,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось применить план');
    } finally {
      setBusy(false);
    }
  };

  const dismiss = async () => {
    if (busy || settled) return;
    setBusy(true);
    setError(null);
    try {
      await onDismiss(plan.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось отклонить план');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="mt-2 rounded-xl border border-white/10 p-3 space-y-2"
      data-testid={`chat-plan-${plan.id}`}
    >
      <p className="text-xs uppercase tracking-widest text-text-secondary">
        Предложение на {plan.plan.entry_date}
      </p>

      <ul className="space-y-1">
        {rows.map((row) => (
          <li key={row.key} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              id={`${plan.id}-${row.key}`}
              checked={ticked.has(row.key)}
              disabled={settled || busy}
              onChange={() => toggle(row.key)}
            />
            <label htmlFor={`${plan.id}-${row.key}`}>{row.label}</label>
          </li>
        ))}

        {plan.plan.journal && (
          <li className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              id={`${plan.id}-journal`}
              checked={journalTicked}
              disabled={settled || busy}
              onChange={() => setJournalTicked((current) => !current)}
            />
            <label htmlFor={`${plan.id}-journal`}>
              текст дня: {plan.plan.journal.content}
            </label>
          </li>
        )}

        {dayPlan && (
          <li className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              id={`${plan.id}-day-plan`}
              checked={dayPlanTicked}
              disabled={settled || busy}
              onChange={() => setDayPlanTicked((current) => !current)}
            />
            <div className="space-y-1">
              <label htmlFor={`${plan.id}-day-plan`}>
                план дня: {lineCount(dayPlanItems(dayPlan).length)}
                {dayPlan.title ? ` — ${dayPlan.title}` : ''}
              </label>
              {dayPlan.op === 'rewrite_day_plan' && (
                <p className="text-xs text-text-secondary">
                  Заменит план дня целиком. Отметка остаётся у строки, чей код в дне
                  уже есть: {dayPlanItems(dayPlan).map((item) => item.code).join(', ')}
                </p>
              )}
            </div>
          </li>
        )}
      </ul>

      {error && <p className="text-sm text-rose-500">{error}</p>}

      {plan.status === 'applied' && (
        <p className="flex items-center gap-1 text-sm text-emerald-500">
          <Check className="w-4 h-4" aria-hidden="true" />
          Записано операций: {plan.operation_count}
          {plan.applied_at ? ` · ${plan.applied_at}` : ''}
        </p>
      )}

      {plan.status === 'dismissed' && (
        <p className="flex items-center gap-1 text-sm text-text-secondary">
          <X className="w-4 h-4" aria-hidden="true" />
          Отклонено
        </p>
      )}

      {plan.status === 'stale' && (
        <p className="text-sm text-text-secondary">
          Устарело: на эту дату уже применён другой план
        </p>
      )}

      {!settled && (
        <div className="flex gap-3">
          <button
            type="button"
            className="text-sm text-lime"
            disabled={busy || chosenCount === 0}
            onClick={() => void apply()}
          >
            {busy ? 'Записываю…' : `Применить (${chosenCount})`}
          </button>
          <button
            type="button"
            className="text-sm text-text-secondary"
            disabled={busy}
            onClick={() => void dismiss()}
          >
            Отклонить
          </button>
        </div>
      )}
    </div>
  );
}
