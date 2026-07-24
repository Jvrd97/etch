'use client';
// [review:need-review] PHASE-01/42-mobile-categories-and-detail
// summary: desktop category detail — chart, entry history, category pager, quick-add and the avoid-streak block unchanged, with the whole batched load now owned by hooks/useCategoryDetail and shared with /m/categories/[id]

import { useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, ArrowRight, Calendar, Plus } from 'lucide-react';
import { type Category } from '@/lib/api';
import { useCategoryDetail } from '@/hooks/useCategoryDetail';
import CategoryChart from '@/components/CategoryChart';
import EntryCard from '@/components/EntryCard';
import EntryForm from '@/components/EntryForm';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import StreakCard from '@/components/StreakCard';

export default function CategoryDetailPage() {
  const params = useParams<{ id: string }>();
  const categoryId = Number(params.id);
  const {
    category,
    categories,
    days,
    entries,
    entryGroups,
    streak,
    invalidId,
    loaded,
    error,
    setError,
    reload,
    prev,
    next,
  } = useCategoryDetail(categoryId);
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="space-y-8 animate-fade-rise">
      <div>
        <Link
          href="/categories"
          className="inline-flex items-center gap-2 text-sm text-text-secondary transition-colors duration-200 hover:text-lime"
        >
          <ArrowLeft className="w-4 h-4" strokeWidth={2} />
          Categories
        </Link>

        <div className="mt-3 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-4xl font-bold text-text-primary tracking-tight">
              {category?.name ?? 'Category'}
              <span className="text-lime">.</span>
            </h1>
            {category?.description && (
              <p className="mt-2 text-text-secondary">{category.description}</p>
            )}
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            <CategoryPagerButton category={prev} direction="prev" />
            <CategoryPagerButton category={next} direction="next" />
            {loaded && (
              <button
                onClick={() => setShowForm(true)}
                className="ml-2 flex items-center gap-2 px-5 py-2.5 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_24px_rgba(184,255,54,0.35)]"
              >
                <Plus className="w-5 h-5" strokeWidth={2} />
                <span className="hidden sm:inline">New entry</span>
              </button>
            )}
          </div>
        </div>

        {categories.length > 1 && (
          <div className="mt-6 flex gap-2 overflow-x-auto pb-1">
            {categories.map((cat) => (
              <Link
                key={cat.id}
                href={`/categories/${cat.id}`}
                aria-current={cat.id === categoryId ? 'page' : undefined}
                className={`px-4 py-2 rounded-3xl text-sm font-medium whitespace-nowrap transition-colors duration-200 ${
                  cat.id === categoryId
                    ? 'bg-lime text-background'
                    : 'bg-surface border border-white/10 text-text-secondary hover:text-text-primary hover:bg-white/5'
                }`}
              >
                {cat.name}
              </Link>
            ))}
          </div>
        )}
      </div>

      {showForm && category && (
        <EntryForm
          categories={categories}
          lockedCategoryId={categoryId}
          onClose={() => setShowForm(false)}
          onSuccess={() => {
            setShowForm(false);
            reload();
          }}
        />
      )}

      {invalidId && <ErrorAlert message="Invalid category id" />}
      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {invalidId ? null : !loaded ? (
        !error && <LoadingSpinner size="lg" />
      ) : (
        <>
          {category.streak_mode === 'avoid' && streak !== null && <StreakCard streak={streak} />}

          <CategoryChart category={category} days={days} />

          {entries.length === 0 ? (
            <div className="text-center py-16 bg-card border border-white/5 rounded-3xl">
              <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
                <Calendar className="w-8 h-8 text-text-disabled" strokeWidth={2} />
              </div>
              <h3 className="text-lg font-medium text-text-primary mb-1">
                No entries yet
              </h3>
              <p className="text-text-secondary">
                Entries for this category will appear here
              </p>
            </div>
          ) : (
            <div className="space-y-8">
              {entryGroups.map(([date, dateEntries]) => (
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
                        category={category}
                        onMutated={reload}
                        onError={setError}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

interface CategoryPagerButtonProps {
  category: Category | null;
  direction: 'prev' | 'next';
}

/** Arrow to the adjacent category; renders a disabled stub at the ends of the list. */
function CategoryPagerButton({ category, direction }: CategoryPagerButtonProps) {
  const Icon = direction === 'prev' ? ArrowLeft : ArrowRight;
  const baseClass = 'p-2.5 rounded-full border transition-colors duration-200';

  if (!category) {
    return (
      <span
        aria-hidden="true"
        className={`${baseClass} border-white/5 text-text-disabled opacity-40`}
      >
        <Icon className="w-5 h-5" strokeWidth={2} />
      </span>
    );
  }

  return (
    <Link
      href={`/categories/${category.id}`}
      aria-label={`${direction === 'prev' ? 'Previous' : 'Next'} category: ${category.name}`}
      title={category.name}
      className={`${baseClass} border-white/10 bg-surface text-text-secondary hover:text-lime hover:border-lime/40`}
    >
      <Icon className="w-5 h-5" strokeWidth={2} />
    </Link>
  );
}
