'use client';
// [review:need-review] PHASE-01/45-mobile-table-sticky-date
// summary: /table desktop page — table state (data load, dynamic columns, tab grouping, checklist toggle) now lives in useTable, shared with /m/table; this page keeps the desktop markup, the day-entries panel and the quick-add flow

import { useEffect, useState } from 'react';
import {
  entriesAPI,
  Entry,
  TableCategoryMeta,
} from '@/lib/api';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import EntryForm from '@/components/EntryForm';
import { DAYS_SHOWN, TRUE_VALUE, columnKey, useTable } from '@/hooks/useTable';
import { formatSecondsToHM } from '@/lib/duration';
import { Check, Plus, Save, Table2, Trash2, X } from 'lucide-react';

interface SelectedCell {
  category: TableCategoryMeta;
  date: string;
}

export default function TablePage() {
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
  const [selected, setSelected] = useState<SelectedCell | null>(null);
  const [quickAdd, setQuickAdd] = useState<SelectedCell | null>(null);

  if (loading) return <LoadingSpinner size="lg" />;

  return (
    <div className="space-y-8 animate-fade-rise">
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          Table
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">
          Last {DAYS_SHOWN} days by group — tap a cell to see the day
        </p>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {tabNames.length === 0 ? (
        <div className="text-center py-16 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <Table2 className="w-8 h-8 text-text-disabled" strokeWidth={2} />
          </div>
          <h3 className="text-lg font-medium text-text-primary mb-1">No columns yet</h3>
          <p className="text-text-secondary">Create a category with at least one field</p>
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
                className={`px-4 py-2 rounded-full text-sm font-medium transition-all duration-200 border ${
                  name === currentTab
                    ? 'bg-lime text-background border-lime shadow-[0_0_18px_rgba(184,255,54,0.25)]'
                    : 'bg-card text-text-secondary border-white/10 hover:text-text-primary hover:bg-white/5'
                }`}
              >
                {name}
              </button>
            ))}
          </div>

          <div className="overflow-x-auto bg-card border border-white/5 rounded-3xl">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10">
                  <th className="px-4 py-3 text-left font-medium text-text-secondary">
                    Day
                  </th>
                  {columns.map((column) => (
                    <th
                      key={columnKey(column)}
                      className="px-4 py-3 text-left font-medium text-text-primary"
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
                    <td className="px-4 py-3 text-text-secondary whitespace-nowrap">
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
                              className={`flex w-full items-center justify-center px-3 py-2 rounded-xl transition-all duration-200 hover:bg-white/5 ${
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
                              value === null
                                ? setQuickAdd({ category: column.category, date: day.date })
                                : setSelected({ category: column.category, date: day.date })
                            }
                            aria-label={`${column.category.name} on ${day.date}`}
                            className={`w-full text-left px-3 py-2 rounded-xl transition-all duration-200 hover:bg-white/5 ${
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

      {selected && (
        <DayEntriesPanel
          category={selected.category}
          date={selected.date}
          onClose={() => setSelected(null)}
          onAddEntry={() => {
            setQuickAdd(selected);
            setSelected(null);
          }}
          onChanged={reload}
          onError={setError}
        />
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

interface DayEntriesPanelProps {
  category: TableCategoryMeta;
  date: string;
  onClose: () => void;
  onAddEntry: () => void;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
}

function DayEntriesPanel({
  category,
  date,
  onClose,
  onAddEntry,
  onChanged,
  onError,
}: DayEntriesPanelProps) {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    entriesAPI
      .getAll({ categoryId: category.id, startDate: date, endDate: date })
      .then((result) => {
        if (!cancelled) setEntries(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          onError(err instanceof Error ? err.message : 'Failed to load entries');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [category.id, date, onError, refreshKey]);

  const refresh = () => setRefreshKey((key) => key + 1);

  const handleDelete = async (entryId: number) => {
    try {
      await entriesAPI.delete(entryId);
      refresh();
      await onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to delete entry');
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`${category.name} entries on ${date}`}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg max-h-[80vh] overflow-y-auto bg-card border border-white/10 rounded-3xl p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">{category.name}</h2>
            <p className="text-sm text-text-secondary">{date}</p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="p-2 rounded-full text-text-secondary transition-colors hover:text-text-primary hover:bg-white/5"
          >
            <X className="w-5 h-5" strokeWidth={2} />
          </button>
        </div>

        {entries === null ? (
          <LoadingSpinner size="sm" />
        ) : entries.length === 0 ? (
          <p className="text-text-secondary py-6 text-center">No entries this day</p>
        ) : (
          entries.map((entry) => (
            <EntryEditor
              key={entry.id}
              entry={entry}
              onSaved={async () => {
                refresh();
                await onChanged();
              }}
              onDelete={() => handleDelete(entry.id)}
              onError={onError}
            />
          ))
        )}

        <button
          onClick={onAddEntry}
          className="flex w-full items-center justify-center gap-2 px-4 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)]"
        >
          <Plus className="w-4 h-4" strokeWidth={2.5} />
          Add entry
        </button>
      </div>
    </div>
  );
}

interface EntryEditorProps {
  entry: Entry;
  onSaved: () => Promise<void>;
  onDelete: () => void;
  onError: (message: string) => void;
}

function EntryEditor({ entry, onSaved, onDelete, onError }: EntryEditorProps) {
  const [values, setValues] = useState<Record<number, string>>(() =>
    Object.fromEntries(entry.values.map((v) => [v.field_id, v.value]))
  );
  const [saving, setSaving] = useState(false);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await entriesAPI.update(entry.id, {
        values: Object.entries(values).map(([fieldId, value]) => ({
          field_id: Number(fieldId),
          value,
        })),
      });
      await onSaved();
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to save entry');
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={handleSave}
      className="bg-surface border border-white/10 rounded-2xl p-4 space-y-3"
    >
      {entry.values.map((entryValue) => (
        <label key={entryValue.id} className="block">
          <span className="text-xs text-text-secondary">
            {entryValue.field?.name ?? `Field #${entryValue.field_id}`}
          </span>
          <input
            type={entryValue.field?.field_type === 'number' ? 'number' : 'text'}
            step="any"
            value={values[entryValue.field_id] ?? ''}
            onChange={(e) =>
              setValues((prev) => ({ ...prev, [entryValue.field_id]: e.target.value }))
            }
            className="mt-1 w-full px-3 py-2 bg-card border border-white/10 rounded-xl text-text-primary outline-none transition-all duration-200 focus:border-lime focus:ring-2 focus:ring-lime/25"
          />
        </label>
      ))}
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Delete entry ${entry.id}`}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm text-red-400 transition-colors hover:bg-red-400/10"
        >
          <Trash2 className="w-4 h-4" strokeWidth={2} />
          Delete
        </button>
        <button
          type="submit"
          disabled={saving}
          className="inline-flex items-center gap-2 px-4 py-2 bg-lime text-background rounded-full text-sm font-medium transition-all duration-200 hover:shadow-[0_0_18px_rgba(184,255,54,0.35)] disabled:opacity-50"
        >
          <Save className="w-4 h-4" strokeWidth={2} />
          Save
        </button>
      </div>
    </form>
  );
}
