'use client';
// [review:need-review] PHASE-01/63-today-card-tap-and-visibility, #176
// summary: Today numeric card supports field units and quick-step buttons that adjust its draft

import { useRef, useState } from 'react';
import { Plus } from 'lucide-react';
import type { Category, Field } from '@/lib/api';
import { quickAddAmount } from '@/lib/quick-add';
import { formatStep, formatValue, quickStepsForField } from '@/lib/format-value';

interface QuickNumberRowProps {
  category: Category;
  /**
   * The field the quick input increments. Undefined for a category the user
   * pinned to Today that has nothing to increment — the card is then only a way
   * into the full editor.
   */
  numberField: Field | undefined;
  /** Sum of today's entries for this field, owned by the Today screen. */
  total: number;
  /**
   * Log `amount` for this field. Resolves false when the save failed, which is
   * the row's only cue to keep the typed value around for a retry; the message
   * itself is the owner's to show.
   */
  onAdd: (amount: number) => Promise<boolean>;
  /** Open the full editor for today's entry in this category. */
  onOpenEditor: () => void;
}

/** Total as a clean string: integers stay integers, floats drop trailing zeros. */
function formatTotal(n: number): string {
  return Number.isInteger(n) ? String(n) : Number(n.toFixed(2)).toString();
}

export default function QuickNumberRow({
  category,
  numberField,
  total,
  onAdd,
  onOpenEditor,
}: QuickNumberRowProps) {
  const [value, setValue] = useState('');
  // Read at submit time rather than mirrored into state: `badInput` is the DOM's
  // own verdict on the text it refused to parse, and a control left in that
  // state fires no further change event to sync from.
  const inputRef = useRef<HTMLInputElement>(null);

  /**
   * One tap, one entry. No in-flight lock and no Idempotency-Key: five taps in a
   * row are five deliberate increments, not a double click to be swallowed.
   */
  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const amount = quickAddAmount(value, {
      hasBadInput: inputRef.current?.validity.badInput ?? false,
    });
    if (amount === null) return;
    const saved = await onAdd(amount);
    // The step is not remembered: once it is banked, the next tap is a 1 again.
    // A failed save keeps the number so the retry is a tap, not retyping it.
    if (saved) setValue('');
  };

  return (
    <form
      onSubmit={handleSave}
      className="flex flex-wrap items-center gap-3 bg-card border border-white/5 rounded-3xl p-4"
    >
      {/*
        The card's own tap target is this button, not the form: an onClick on the
        wrapper would fire for the number input and the "+" as well, and every
        quick increment would drag the editor open behind it. Bounded to the
        name block, it cannot overlap the controls at all.
      */}
      <button
        type="button"
        onClick={onOpenEditor}
        aria-label={`Open today's ${category.name} entry`}
        className="min-w-0 flex-1 text-left"
      >
        <span className="block text-sm font-medium text-text-primary truncate">
          {category.name}
        </span>
        <span className="block text-xs text-text-disabled truncate">
          {numberField ? numberField.name : 'Tap to log'}
        </span>
      </button>
      {numberField && (
        <>
          <div className="text-right leading-tight">
            {/*
              Keyed by the total so every change remounts the node and replays the
              animation: on rapid taps a restyled node would keep the finished
              animation and the later increments would land silently.
            */}
            <span
              key={total}
              className="block text-2xl font-semibold text-lime tabular-nums animate-total-bump"
            >
              {formatValue(formatTotal(total), numberField.unit)}
            </span>
            <span className="block text-[11px] uppercase tracking-widest text-text-disabled">
              today
            </span>
          </div>
          <input
            ref={inputRef}
            type="number"
            step="any"
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="0"
            aria-label={`${category.name}: add ${numberField.name}`}
            className="w-20 sm:w-24 px-3 sm:px-4 py-2.5 bg-surface border border-white/10 rounded-2xl text-text-primary placeholder:text-text-disabled outline-none transition-all duration-200 focus:border-lime focus:ring-2 focus:ring-lime/25"
          />
          {quickStepsForField(numberField.quick_steps).map((step) => (
            <button
              key={step}
              type="button"
              onClick={() => setValue(String((Number(value) || 0) + step))}
              aria-label={`Adjust ${category.name} by ${formatStep(step, numberField.unit)}`}
              className="px-2 py-2 bg-surface border border-white/10 rounded-xl text-xs text-text-primary"
            >
              {formatStep(step, numberField.unit)}
            </button>
          ))}
          <button
            type="submit"
            aria-label={`Add to ${category.name}`}
            className="p-2.5 bg-lime text-background rounded-full transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_18px_rgba(184,255,54,0.35)]"
          >
            <Plus className="w-4 h-4" strokeWidth={2.5} />
          </button>
        </>
      )}
    </form>
  );
}
