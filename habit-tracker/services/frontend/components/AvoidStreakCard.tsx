'use client';
// [review:need-review] PHASE-01/28-today-avoid-card, PHASE-01/201
// summary: Today avoid streak card saves a sole boolean fact in one tap with exact undo, while numeric and composite categories retain their form

import { useRef, useState } from 'react';
import { AlertCircle, Flame } from 'lucide-react';
import { Category, CategoryStreak, Entry, Field, entriesAPI } from '@/lib/api';
import { formatCleanDays, formatDays } from '@/lib/streak-format';
import { todayISO } from '@/lib/date';
import { newTapKey } from '@/lib/quick-marks';

interface AvoidStreakCardProps {
  category: Category;
  /** Optional "how much" field the relapse amount is recorded into. */
  numberField: Field | undefined;
  /** Today's entries let the card restore a previously saved boolean fact. */
  entries: Entry[];
  /** Streak data, or null while loading / when the endpoint failed. */
  streak: CategoryStreak | null;
  /** Called after a relapse is saved so the parent can refetch the streak. */
  onRelapse: (categoryId: number) => void;
  /** Replaces the day's entry snapshot after a quick mark or its undo. */
  onEntriesChanged: () => Promise<void>;
  onError: (message: string) => void;
}

export default function AvoidStreakCard({
  category,
  numberField,
  entries,
  streak,
  onRelapse,
  onEntriesChanged,
  onError,
}: AvoidStreakCardProps) {
  const [showForm, setShowForm] = useState(false);
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [quickBooleanEntryId, setQuickBooleanEntryId] = useState<number | null>(null);
  const [ignoredBooleanEntryId, setIgnoredBooleanEntryId] = useState<number | null>(null);
  const quickBooleanKey = useRef<string | null>(null);

  const booleanFields = category.fields.filter((field) => field.field_type === 'boolean');
  const booleanField = booleanFields.length === 1 ? booleanFields[0] : undefined;
  const isQuickBoolean = category.fields.length === 1 && booleanField !== undefined;
  const hasSavedBooleanMark =
    booleanField !== undefined &&
    entries.some(
      (entry) =>
        entry.category_id === category.id &&
        entry.id !== ignoredBooleanEntryId &&
        entry.values.some(
          (value) => value.field_id === booleanField.id && value.value === 'true'
        )
    );
  const isBooleanMarked = quickBooleanEntryId !== null || hasSavedBooleanMark;

  const resetForm = () => {
    setAmount('');
    setNote('');
    setShowForm(false);
  };

  const refreshEntries = async () => {
    try {
      await onEntriesChanged();
    } catch {
      onError('Список записей не обновился');
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;

    const values =
      numberField && amount && Number.isFinite(Number(amount))
        ? [{ field_id: numberField.id, value: amount }]
        : [];

    setSaving(true);
    try {
      await entriesAPI.create({
        category_id: category.id,
        entry_date: todayISO(),
        notes: note.trim() || undefined,
        values,
      });
      resetForm();
      onRelapse(category.id);
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to record relapse');
    } finally {
      setSaving(false);
    }
  };

  const markBoolean = async () => {
    if (saving || booleanField === undefined) return;

    const idempotencyKey = quickBooleanKey.current ?? newTapKey();
    quickBooleanKey.current = idempotencyKey;
    setSaving(true);
    try {
      const entry = await entriesAPI.create({
        category_id: category.id,
        entry_date: todayISO(),
        values: [{ field_id: booleanField.id, value: 'true' }],
      }, idempotencyKey);
      setQuickBooleanEntryId(entry.id);
      setIgnoredBooleanEntryId(null);
      quickBooleanKey.current = null;
      await refreshEntries();
      onRelapse(category.id);
    } catch {
      onError('Не удалось сохранить отметку');
    } finally {
      setSaving(false);
    }
  };

  const undoBooleanMark = async () => {
    if (saving || quickBooleanEntryId === null) return;

    setSaving(true);
    try {
      await entriesAPI.delete(quickBooleanEntryId);
      setQuickBooleanEntryId(null);
      setIgnoredBooleanEntryId(quickBooleanEntryId);
      await refreshEntries();
      onRelapse(category.id);
    } catch {
      onError('Не удалось отменить отметку');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-card border border-white/5 rounded-3xl p-6">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <Flame className="w-4 h-4 text-lime" strokeWidth={2} />
            <span className="text-[13px] font-medium uppercase tracking-widest text-lime truncate">
              {category.name}
            </span>
          </div>
          <p className="text-4xl font-bold text-lime tracking-tight tabular-nums">
            {streak ? formatCleanDays(streak.current_streak) : '—'}
          </p>
          {streak && (
            <p className="mt-1 text-xs text-text-disabled">
              Best {formatDays(streak.best_streak)}
            </p>
          )}
        </div>

        {isQuickBoolean && isBooleanMarked && quickBooleanEntryId === null && (
          <span role="status" className="text-sm font-medium text-text-secondary">
            Случилось
          </span>
        )}
        {isQuickBoolean && quickBooleanEntryId !== null && (
          <button
            type="button"
            onClick={undoBooleanMark}
            disabled={saving}
            className="px-4 py-2.5 rounded-full text-sm font-medium bg-surface border border-white/10 text-text-secondary transition-all duration-200 hover:text-text-primary hover:border-white/20 disabled:opacity-50"
          >
            Отменить
          </button>
        )}
        {isQuickBoolean && !isBooleanMarked && (
          <button
            type="button"
            onClick={markBoolean}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2.5 rounded-full text-sm font-medium bg-surface border border-white/10 text-text-secondary transition-all duration-200 hover:text-text-primary hover:border-white/20 disabled:opacity-50"
          >
            <AlertCircle className="w-4 h-4" strokeWidth={2} />
            Случилось
          </button>
        )}
        {!isQuickBoolean && !showForm && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-full text-sm font-medium bg-surface border border-white/10 text-text-secondary transition-all duration-200 hover:text-text-primary hover:border-white/20"
          >
            <AlertCircle className="w-4 h-4" strokeWidth={2} />
            Случилось
          </button>
        )}
      </div>

      {showForm && (
        <form onSubmit={handleSave} className="mt-5 space-y-3">
          {numberField && (
            <div>
              <label className="block text-xs text-text-disabled mb-1">
                {numberField.name}
              </label>
              <input
                type="number"
                step="any"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="0"
                aria-label={`${category.name}: ${numberField.name}`}
                className="w-full px-4 py-2.5 bg-surface border border-white/10 rounded-2xl text-text-primary placeholder:text-text-disabled outline-none transition-all duration-200 focus:border-lime focus:ring-2 focus:ring-lime/25"
              />
            </div>
          )}
          <div>
            <label className="block text-xs text-text-disabled mb-1">Заметка</label>
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Что случилось?"
              aria-label={`${category.name}: note`}
              className="w-full px-4 py-2.5 bg-surface border border-white/10 rounded-2xl text-text-primary placeholder:text-text-disabled outline-none transition-all duration-200 focus:border-lime focus:ring-2 focus:ring-lime/25"
            />
          </div>
          <div className="flex items-center gap-3 pt-1">
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2.5 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_18px_rgba(184,255,54,0.35)] disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-none"
            >
              {saving ? 'Сохранение…' : 'Сохранить'}
            </button>
            <button
              type="button"
              onClick={resetForm}
              disabled={saving}
              className="px-5 py-2.5 rounded-3xl font-medium text-text-secondary transition-colors duration-200 hover:text-text-primary disabled:opacity-50"
            >
              Отмена
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
