// [review:need-review] #176
// summary: shared desktop/mobile Continue tracking cards from Today category semantics

import Link from 'next/link';
import { ArrowRight, Plus } from 'lucide-react';
import type { Category, Entry } from '@/lib/api';
import { formatValue } from '@/lib/format-value';
import { newEntryHref } from '@/lib/routes';
import { firstNumberField, partitionTodayCategories } from '@/lib/today-categories';

interface ContinueTrackingProps {
  categories: Category[];
  entries: Entry[];
  mobile?: boolean;
}

export function ContinueTracking({ categories, entries, mobile = false }: ContinueTrackingProps) {
  const groups = partitionTodayCategories(categories.filter((category) => category.is_active));
  const items = [
    ...groups.quickForm,
    ...groups.checklist.map((category) => ({ category, numberField: firstNumberField(category) })),
    ...groups.avoid,
  ];
  const prefix = mobile ? '/m' : '';

  return (
    <section aria-labelledby="continue-tracking-title">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <h2 id="continue-tracking-title" className="text-[22px] font-semibold text-text-primary">Continue tracking</h2>
          <p className="text-[13px] text-text-secondary">Quick add for your habits</p>
        </div>
        <Link href={`${prefix}/categories`} className="text-sm text-text-secondary">Manage</Link>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {items.map(({ category, numberField }) => {
          const lastEntry = entries
            .filter(
              (entry) =>
                entry.category_id === category.id &&
                numberField !== undefined &&
                entry.values.some((value) => value.field_id === numberField.id)
            )
            .reduce<Entry | undefined>((latest, entry) => {
              if (!latest) return entry;
              if (entry.entry_date !== latest.entry_date) {
                return entry.entry_date > latest.entry_date ? entry : latest;
              }
              return entry.id > latest.id ? entry : latest;
            }, undefined);
          const raw = numberField && lastEntry?.values.find((value) => value.field_id === numberField.id)?.value;
          return (
            <article key={category.id} className="bg-card border border-white/5 rounded-2xl p-4 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium text-text-primary truncate">{category.name}</p>
                <p className="text-xs text-text-disabled truncate">Last: {raw === undefined ? '—' : formatValue(raw, numberField?.unit)}</p>
              </div>
              <Link
                href={numberField ? `${prefix}${newEntryHref(category.id)}` : `${prefix}/categories/${category.id}`}
                aria-label={numberField ? `Add ${category.name} entry` : `Open ${category.name} editor`}
                className="shrink-0 rounded-full bg-lime text-background p-2"
              >
                {numberField ? <Plus className="w-4 h-4" /> : <ArrowRight className="w-4 h-4" />}
              </Link>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export default ContinueTracking;
