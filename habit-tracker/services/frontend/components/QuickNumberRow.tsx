'use client';
// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: quick number input row for Today (running total + add), extracted from app/today/page.tsx so /m/today reuses it

import { useState } from 'react';
import { Plus } from 'lucide-react';
import { entriesAPI, type Category, type Field } from '@/lib/api';
import { todayISO } from '@/lib/date';

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
  const [saving, setSaving] = useState(false);
  const [total, setTotal] = useState(initialTotal);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const amount = Number(value);
    if (!value || !Number.isFinite(amount)) return;
    setSaving(true);
    try {
      await entriesAPI.create({
        category_id: category.id,
        entry_date: todayISO(),
        values: [{ field_id: numberField.id, value }],
      });
      setTotal((current) => current + amount);
      setValue('');
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to save entry');
    } finally {
      setSaving(false);
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
        disabled={saving || !value}
        aria-label={`Add to ${category.name}`}
        className="p-2.5 bg-lime text-background rounded-full transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_18px_rgba(184,255,54,0.35)] disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-none"
      >
        <Plus className="w-4 h-4" strokeWidth={2.5} />
      </button>
    </form>
  );
}
