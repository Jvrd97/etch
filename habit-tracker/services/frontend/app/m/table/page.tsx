'use client';
// [review:need-review] PHASE-01/45-mobile-table-sticky-date
// summary: mobile Table screen — same date × category grid as the desktop page via useTable, but horizontal scroll is confined to the table container with the date column pinned left (sticky, own opaque background) so it never scrolls out of view; cell text stays at text-sm to read without a zoom

import { useState } from 'react';
import { Check, Table2 } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import EntryForm from '@/components/EntryForm';
import { TRUE_VALUE, columnKey, useTable } from '@/hooks/useTable';
import type { TableCategoryMeta } from '@/lib/api';
import { formatSecondsToHM } from '@/lib/duration';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

/** A table cell the user tapped to add an entry for. */
interface QuickAddTarget {
  category: TableCategoryMeta;
  date: string;
}

/**
 * The date column is pinned to the left edge while the categories scroll under
 * it. It carries its own opaque `bg-card` so the scrolling cells never show
 * through, and a higher stacking context than the body cells that slide beneath.
 */
const STICKY_DATE_CELL = 'sticky left-0 z-10 bg-card';

export default function MobileTablePage() {
  const {
    loading,
    error,
    setError,
    categories,
    tabNames,
    currentTab,
    setActiveTab,
    columns,
    days,
    cellValue,
    handleToggle,
    reload,
  } = useTable();
  const [quickAdd, setQuickAdd] = useState<QuickAddTarget | null>(null);

  if (loading) return <LoadingSpinner size="lg" />;

  return (
    <div className="space-y-5 animate-fade-rise">
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {tabNames.length === 0 ? (
        <div className="text-center py-12 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <Table2 className="w-7 h-7 text-text-disabled" strokeWidth={2} />
          </div>
          <h2 className="text-base font-medium text-text-primary mb-1">No columns yet</h2>
          <p className="text-sm text-text-secondary px-6">
            Create a category with at least one field
          </p>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Category groups">
            {tabNames.map((name) => (
              <button
                key={name}
                role="tab"
                aria-selected={name === currentTab}
                onClick={() => setActiveTab(name)}
                style={{ minHeight: TAP_TARGET_PX }}
                className={`px-4 py-2 rounded-full text-sm font-medium transition-colors duration-200 border ${
                  name === currentTab
                    ? 'bg-lime text-background border-lime'
                    : 'bg-card text-text-secondary border-white/10 active:bg-white/5'
                }`}
              >
                {name}
              </button>
            ))}
          </div>

          <div className="overflow-x-auto bg-card border border-white/5 rounded-3xl">
            <table className="w-max text-sm">
              <thead>
                <tr className="border-b border-white/10">
                  <th
                    className={`${STICKY_DATE_CELL} z-20 px-4 py-3 text-left font-medium text-text-secondary`}
                  >
                    Day
                  </th>
                  {columns.map((column) => (
                    <th
                      key={columnKey(column)}
                      className="px-4 py-3 text-left font-medium text-text-primary whitespace-nowrap"
                    >
                      {column.kind === 'check' ? column.fieldName : column.category.name}
                      <span className="block text-xs font-normal text-text-disabled">
                        {column.kind === 'check'
                          ? column.category.name
                          : column.category.primary_field_name}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {days.map((day) => (
                  <tr key={day.date} className="border-b border-white/5 last:border-b-0">
                    <td
                      className={`${STICKY_DATE_CELL} px-4 py-3 text-text-secondary whitespace-nowrap`}
                    >
                      {day.date}
                    </td>
                    {columns.map((column) => {
                      const value = cellValue(day.date, column.category.id, column.fieldId);
                      if (column.kind === 'check') {
                        const isChecked = value === TRUE_VALUE;
                        return (
                          <td key={columnKey(column)} className="px-1 py-1">
                            <button
                              onClick={() =>
                                handleToggle(column.category.id, column.fieldId, day.date)
                              }
                              aria-pressed={isChecked}
                              aria-label={`${column.category.name}: ${column.fieldName} on ${day.date}`}
                              style={{ minHeight: TAP_TARGET_PX }}
                              className={`flex w-full items-center justify-center px-3 py-2 rounded-xl transition-colors duration-200 active:bg-white/5 ${
                                isChecked ? 'text-lime' : 'text-text-disabled'
                              }`}
                            >
                              {isChecked ? (
                                <Check className="w-4 h-4" strokeWidth={2.5} />
                              ) : (
                                <span aria-hidden="true">—</span>
                              )}
                            </button>
                          </td>
                        );
                      }
                      const displayValue =
                        value !== null && column.category.primary_field_type === 'duration'
                          ? formatSecondsToHM(Number(value))
                          : value;
                      return (
                        <td key={columnKey(column)} className="px-1 py-1">
                          <button
                            onClick={() =>
                              setQuickAdd({ category: column.category, date: day.date })
                            }
                            aria-label={`${column.category.name} on ${day.date}`}
                            style={{ minHeight: TAP_TARGET_PX }}
                            className={`w-full text-left px-3 py-2 rounded-xl whitespace-nowrap transition-colors duration-200 active:bg-white/5 ${
                              value !== null ? 'text-lime font-medium' : 'text-text-disabled'
                            }`}
                          >
                            {displayValue ?? '—'}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {quickAdd && (
        <EntryForm
          categories={categories}
          lockedCategoryId={quickAdd.category.id}
          date={quickAdd.date}
          onClose={() => setQuickAdd(null)}
          onSuccess={() => {
            setQuickAdd(null);
            void reload();
          }}
        />
      )}
    </div>
  );
}
