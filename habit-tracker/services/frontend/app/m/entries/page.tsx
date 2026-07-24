'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/42-mobile-categories-and-detail
// summary: mobile Entries screen — same data as the desktop page via useEntries, creation and editing done in the shared EntryEditorSheet, ?new=1 opening the editor on mount, with a dedicated empty state when no category exists yet

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Calendar, FolderPlus, Pencil, Plus, X } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import EntryEditorSheet, { UNKNOWN_CATEGORY_NAME } from '@/components/mobile/EntryEditorSheet';
import { useEntries } from '@/hooks/useEntries';
import { entriesAPI, type Category, type Entry } from '@/lib/api';
import { labelledValues } from '@/lib/entry-values';
import { MOBILE_PATH_PREFIX, wantsNewEntry } from '@/lib/routes';
import { TAP_TARGET_PX, entryInputClass } from '@/lib/ui-constants';

/** What the editor sheet is currently doing; closed when null. */
type SheetState = { kind: 'create' } | { kind: 'edit'; entry: Entry };

/**
 * Accessible name of the FAB and title of the sheet it opens.
 *
 * Deliberately different strings: a button and a dialog carrying the same name
 * are two indistinguishable nodes in the accessibility tree, and "New entry"
 * read out over an already-open editor says nothing about where you are.
 */
const NEW_ENTRY_BUTTON_LABEL = 'New entry';

/**
 * Where the empty state sends the user to define their first category.
 *
 * Deliberately the `/m` twin rather than the desktop route: `MobileRestore`
 * redirects into the mobile shell once per session, so a link out to
 * `/categories` drops the user into the desktop screen with nothing to bring
 * them back.
 */
const CATEGORIES_HREF = `${MOBILE_PATH_PREFIX}/categories`;

export default function MobileEntriesPage() {
  // useSearchParams needs a Suspense boundary for static prerendering
  return (
    <Suspense fallback={<LoadingSpinner size="lg" />}>
      <MobileEntriesPageContent />
    </Suspense>
  );
}

function MobileEntriesPageContent() {
  const searchParams = useSearchParams();
  const {
    categories,
    entries,
    grouped,
    loading,
    error,
    filterCategory,
    setFilterCategory,
    setError,
    reload,
    categoryOf,
  } = useEntries();
  // Read once, as the initial state rather than in an effect: the sheet has to
  // be on screen from the first paint, and a later change of the param without
  // a remount is not a thing the shell does.
  const [sheet, setSheet] = useState<SheetState | null>(() =>
    wantsNewEntry(searchParams) ? { kind: 'create' } : null
  );

  const handleDelete = async (entry: Entry, categoryName: string) => {
    if (!confirm(`Delete this ${categoryName} entry?`)) return;
    try {
      await entriesAPI.delete(entry.id);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete entry');
    }
  };

  if (loading) return <LoadingSpinner size="lg" />;

  // The page-level banner reports what happened to the list itself — a failed
  // load or delete. A failed save belongs inside the sheet, where the user is.
  const listError = error && <ErrorAlert message={error} onDismiss={() => setError(null)} />;

  // Without a category there is nothing to log into: the sheet would open on an
  // empty picker and post `category_id: 0`.
  if (categories.length === 0) {
    return (
      <div className="space-y-5 animate-fade-rise">
        {listError}
        <div className="text-center py-12 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <FolderPlus className="w-7 h-7 text-text-disabled" strokeWidth={2} />
          </div>
          <h2 className="text-base font-medium text-text-primary mb-1">Create a category first</h2>
          <p className="text-sm text-text-secondary px-6 mb-5">
            Entries are logged into a category, so there is nothing to fill in yet.
          </p>
          <Link
            href={CATEGORIES_HREF}
            style={{ minHeight: TAP_TARGET_PX }}
            className="inline-flex items-center justify-center px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-transform duration-200 active:scale-95"
          >
            Go to Categories
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-rise">
      {listError}

      <select
        aria-label="Filter by category"
        value={filterCategory ?? ''}
        onChange={(e) => setFilterCategory(e.target.value ? Number(e.target.value) : null)}
        style={{ minHeight: TAP_TARGET_PX }}
        className={entryInputClass}
      >
        <option value="">All categories</option>
        {categories.map((category) => (
          <option key={category.id} value={category.id}>
            {category.name}
          </option>
        ))}
      </select>

      {entries.length === 0 ? (
        <div className="text-center py-12 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <Calendar className="w-7 h-7 text-text-disabled" strokeWidth={2} />
          </div>
          <h2 className="text-base font-medium text-text-primary mb-1">Nothing here yet</h2>
          <p className="text-sm text-text-secondary px-6">
            Tap the plus button to log your first entry
          </p>
        </div>
      ) : (
        grouped.map(([date, dateEntries]) => (
          <section key={date}>
            <div className="flex items-center gap-3 mb-3">
              <span className="text-[12px] font-medium uppercase tracking-widest text-lime truncate">
                {date}
              </span>
              <div className="flex-1 h-px bg-white/5" />
            </div>
            <div className="space-y-3">
              {dateEntries.map((entry) => (
                <EntryRow
                  key={entry.id}
                  entry={entry}
                  category={categoryOf(entry)}
                  onEdit={() => setSheet({ kind: 'edit', entry })}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          </section>
        ))
      )}

      <button
        onClick={() => setSheet({ kind: 'create' })}
        aria-label={NEW_ENTRY_BUTTON_LABEL}
        style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
        className="fixed bottom-20 right-5 z-40 p-4 bg-lime text-background rounded-full shadow-[0_8px_24px_rgba(0,0,0,0.45)] transition-transform duration-200 active:scale-95"
      >
        <Plus className="w-6 h-6" strokeWidth={2.5} />
      </button>

      {sheet && (
        <EntryEditorSheet
          // Remounting per target keeps the draft state trivially correct: a
          // freshly opened sheet never inherits the previous entry's values.
          key={sheet.kind === 'edit' ? sheet.entry.id : 'new'}
          categories={categories}
          entry={sheet.kind === 'edit' ? sheet.entry : null}
          onCancel={() => setSheet(null)}
          onSaved={async () => {
            setSheet(null);
            await reload();
          }}
        />
      )}
    </div>
  );
}

interface EntryRowProps {
  entry: Entry;
  category: Category | undefined;
  onEdit: () => void;
  onDelete: (entry: Entry, categoryName: string) => void;
}

/** One entry in the mobile list: a summary line plus edit and delete actions. */
function EntryRow({ entry, category, onEdit, onDelete }: EntryRowProps) {
  const categoryName = category?.name ?? UNKNOWN_CATEGORY_NAME;
  const values = labelledValues(category, entry);

  return (
    <div className="bg-card border border-white/5 rounded-3xl p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[15px] font-medium text-text-primary truncate">{categoryName}</h3>
        <div className="flex items-center gap-1 shrink-0">
          {category && (
            <button
              onClick={onEdit}
              aria-label={`Edit ${categoryName} entry`}
              style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
              className="inline-flex items-center justify-center rounded-full text-text-secondary transition-colors duration-200 active:text-lime"
            >
              <Pencil className="w-4 h-4" strokeWidth={2} />
            </button>
          )}
          <button
            onClick={() => onDelete(entry, categoryName)}
            aria-label={`Delete ${categoryName} entry`}
            style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
            className="inline-flex items-center justify-center rounded-full text-text-secondary transition-colors duration-200 active:text-danger"
          >
            <X className="w-4 h-4" strokeWidth={2} />
          </button>
        </div>
      </div>

      {values.length > 0 && (
        <dl className="mt-3 grid grid-cols-2 gap-2">
          {values.map(({ id, label, value }) => (
            <div key={id} className="bg-surface border border-white/5 rounded-2xl p-3">
              <dt className="text-xs text-text-disabled mb-0.5 truncate">{label}</dt>
              <dd className="text-sm font-medium text-text-primary break-words">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {entry.notes && <p className="mt-3 text-sm text-text-secondary">{entry.notes}</p>}
    </div>
  );
}
