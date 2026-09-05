'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, #176
// summary: desktop /entries page — data, filter and reload now come from useEntries, shared with /m/entries; markup unchanged apart from a label on the filter

import { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import EntryCard from '@/components/EntryCard';
import EntryForm from '@/components/EntryForm';
import { useEntries } from '@/hooks/useEntries';
import { newEntryCategoryId, wantsNewEntry } from '@/lib/routes';
import { Plus, Filter, Calendar } from 'lucide-react';

export default function EntriesPage() {
  // useSearchParams needs a Suspense boundary for static prerendering
  return (
    <Suspense fallback={<LoadingSpinner size="lg" />}>
      <EntriesPageContent />
    </Suspense>
  );
}

function EntriesPageContent() {
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
  const [showForm, setShowForm] = useState(wantsNewEntry(searchParams));

  if (loading) return <LoadingSpinner size="lg" />;

  return (
    <div className="space-y-8 animate-fade-rise">
      <div className="flex justify-between items-center gap-4">
        <div>
          <h1 className="text-4xl font-bold text-text-primary tracking-tight">
            Entries
            <span className="text-lime">.</span>
          </h1>
          <p className="mt-2 text-text-secondary">Track your daily data</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)]"
        >
          <Plus className="w-5 h-5" strokeWidth={2} />
          <span className="hidden sm:inline">New entry</span>
        </button>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Filter */}
      <div className="bg-card border border-white/5 rounded-3xl p-4">
        <div className="flex items-center gap-4">
          <div className="p-2 rounded-2xl bg-surface flex-shrink-0">
            <Filter className="w-4 h-4 text-lime" strokeWidth={2} />
          </div>
          <select
            aria-label="Filter by category"
            value={filterCategory ?? ''}
            onChange={(e) => setFilterCategory(e.target.value ? Number(e.target.value) : null)}
            className="flex-1 px-4 py-2.5 bg-surface border border-white/10 rounded-2xl text-text-primary outline-none transition-all duration-200 focus:border-lime focus:ring-2 focus:ring-lime/25"
          >
            <option value="">All categories</option>
            {categories.map((cat) => (
              <option key={cat.id} value={cat.id}>
                {cat.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Entry Form Modal */}
      {showForm && (
        <EntryForm
          categories={categories}
          initialCategoryId={newEntryCategoryId(searchParams) ?? undefined}
          onClose={() => setShowForm(false)}
          onSuccess={() => {
            setShowForm(false);
            void reload();
          }}
        />
      )}

      {/* Entries List grouped by date */}
      {entries.length === 0 ? (
        <div className="text-center py-16 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <Calendar className="w-8 h-8 text-text-disabled" strokeWidth={2} />
          </div>
          <h3 className="text-lg font-medium text-text-primary mb-1">Nothing here yet</h3>
          <p className="text-text-secondary mb-6">Start tracking by creating your first entry</p>
          <button
            onClick={() => setShowForm(true)}
            className="px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)]"
          >
            Create entry
          </button>
        </div>
      ) : (
        <div className="space-y-8">
          {grouped.map(([date, dateEntries]) => (
            <div key={date}>
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[13px] font-medium uppercase tracking-widest text-lime">
                  {date}
                </span>
                <div className="flex-1 h-px bg-white/5" />
              </div>
              <div className="space-y-4">
                {dateEntries.map((entry) => (
                  <EntryCard
                    key={entry.id}
                    entry={entry}
                    category={categoryOf(entry)}
                    onMutated={() => void reload()}
                    onError={setError}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Floating action button: always reachable without scrolling */}
      <button
        onClick={() => setShowForm(true)}
        aria-label="New entry"
        className="fixed bottom-6 right-6 z-40 p-4 bg-lime text-background rounded-full shadow-[0_8px_24px_rgba(0,0,0,0.45)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.45)]"
      >
        <Plus className="w-6 h-6" strokeWidth={2.5} />
      </button>
    </div>
  );
}
