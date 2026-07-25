'use client';
// [review:need-review] PHASE-01/60-quick-plus-tap-adds-one
// summary: quick number input row for Today (running total + add); the "+" now logs 1 on an empty field and never disables itself

import { useRef, useState } from 'react';
import { Plus } from 'lucide-react';
import { entriesAPI, type Category, type Field } from '@/lib/api';
import { todayISO } from '@/lib/date';
import { quickAddAmount } from '@/lib/quick-add';

interface QuickNumberRowProps {
  category: Category;
  numberField: Field;
  /** Sum of today's entries for this field, shown as the running total. */
  initialTotal: number;
  onError: (message: string) => void;
}

/** Total as a clean string: integers stay integers, floats drop trailing zeros. */
function formatTotal(n: number): string {
  return Number.isInteger(n) ? String(n) : Number(n.toFixed(2)).toString();
}

export default function QuickNumberRow({
  category,
  numberField,
  initialTotal,
  onError,
}: QuickNumberRowProps) {
  const [value, setValue] = useState('');
  const [total, setTotal] = useState(initialTotal);
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
    try {
      await entriesAPI.create({
        category_id: category.id,
        entry_date: todayISO(),
        values: [{ field_id: numberField.id, value: String(amount) }],
      });
      setTotal((current) => current + amount);
      // The step is not remembered: once it is banked, the next tap is a 1 again.
      // A failed save keeps the number so the retry is a tap, not retyping it.
      setValue('');
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to save entry');
    }
  };

  return (
    <form
      onSubmit={handleSave}
      className="flex items-center gap-4 bg-card border border-white/5 rounded-3xl p-4"
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-text-primary truncate">{category.name}</p>
        <p className="text-xs text-text-disabled truncate">{numberField.name}</p>
      </div>
      <div className="text-right leading-tight">
        <span className="block text-2xl font-semibold text-lime tabular-nums">
          {formatTotal(total)}
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
      <button
        type="submit"
        aria-label={`Add to ${category.name}`}
        className="p-2.5 bg-lime text-background rounded-full transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_18px_rgba(184,255,54,0.35)]"
      >
        <Plus className="w-4 h-4" strokeWidth={2.5} />
      </button>
    </form>
  );
}
