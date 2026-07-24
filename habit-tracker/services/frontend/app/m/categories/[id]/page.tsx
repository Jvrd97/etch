'use client';
// [review:need-review] PHASE-01/42-mobile-categories-and-detail
// summary: mobile category detail — same data as the desktop page via useCategoryDetail, links kept inside the /m shell, the category strip scrolling inside itself instead of widening the page, and quick-add through the shared EntryEditorSheet locked to this category

import { useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, ArrowRight, Calendar, Plus } from 'lucide-react';
import CategoryChart from '@/components/CategoryChart';
import EntryCard from '@/components/EntryCard';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import StreakCard from '@/components/StreakCard';
import EntryEditorSheet from '@/components/mobile/EntryEditorSheet';
import { useCategoryDetail } from '@/hooks/useCategoryDetail';
import type { Category } from '@/lib/api';
import { MOBILE_PATH_PREFIX } from '@/lib/routes';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

/** Mobile list screen this detail page belongs to. */
const CATEGORIES_HREF = `${MOBILE_PATH_PREFIX}/categories`;

/** Mobile detail route of `id` — the strip and the pager must not fall back to desktop. */
function categoryHref(id: number): string {
  return `${CATEGORIES_HREF}/${id}`;
}

/** Accessible name of the button opening the quick-add sheet. */
const NEW_ENTRY_BUTTON_LABEL = 'New entry';

export default function MobileCategoryDetailPage() {
  const params = useParams<{ id: string }>();
  const categoryId = Number(params.id);
  const detail = useCategoryDetail(categoryId);
  const [sheetOpen, setSheetOpen] = useState(false);

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
  } = detail;

  return (
    <div className="space-y-5 animate-fade-rise">
      <Link
        href={CATEGORIES_HREF}
        style={{ minHeight: TAP_TARGET_PX }}
        className="inline-flex items-center gap-2 text-sm text-text-secondary"
      >
        <ArrowLeft className="w-4 h-4" strokeWidth={2} />
        Categories
      </Link>

      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-text-primary tracking-tight truncate">
            {category?.name ?? 'Category'}
            <span className="text-lime">.</span>
          </h1>
          {category?.description && (
            <p className="mt-1 text-sm text-text-secondary">{category.description}</p>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <CategoryPagerButton category={prev} direction="prev" />
          <CategoryPagerButton category={next} direction="next" />
        </div>
      </div>

      {categories.length > 1 && (
        <nav
          aria-label="Categories"
          // Scrolls inside itself: pills that wrap would grow the header on every
          // extra category, and pills that overflow would give the whole body a
          // horizontal scrollbar.
          className="-mx-4 px-4 flex gap-2 overflow-x-auto pb-1"
        >
          {categories.map((option) => (
            <Link
              key={option.id}
              href={categoryHref(option.id)}
              aria-current={option.id === categoryId ? 'page' : undefined}
              style={{ minHeight: TAP_TARGET_PX }}
              className={`inline-flex items-center px-4 py-2 rounded-3xl text-sm font-medium whitespace-nowrap shrink-0 transition-colors duration-200 ${
                option.id === categoryId
                  ? 'bg-lime text-background'
                  : 'bg-surface border border-white/10 text-text-secondary'
              }`}
            >
              {option.name}
            </Link>
          ))}
        </nav>
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
            <div className="text-center py-12 bg-card border border-white/5 rounded-3xl">
              <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
                <Calendar className="w-7 h-7 text-text-disabled" strokeWidth={2} />
              </div>
              <h2 className="text-base font-medium text-text-primary mb-1">No entries yet</h2>
              <p className="text-sm text-text-secondary px-6">
                Tap the plus button to log your first one
              </p>
            </div>
          ) : (
            <div className="space-y-6">
              {entryGroups.map(([date, dateEntries]) => (
                <section key={date}>
                  <div className="flex items-center gap-3 mb-3">
                    <span className="text-[12px] font-medium uppercase tracking-widest text-lime truncate">
                      {date}
                    </span>
                    <div className="flex-1 h-px bg-white/5" />
                  </div>
                  <div className="space-y-3">
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
                </section>
              ))}
            </div>
          )}

          <button
            onClick={() => setSheetOpen(true)}
            aria-label={NEW_ENTRY_BUTTON_LABEL}
            style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
            className="fixed bottom-20 right-5 z-40 p-4 bg-lime text-background rounded-full shadow-[0_8px_24px_rgba(0,0,0,0.45)] transition-transform duration-200 active:scale-95"
          >
            <Plus className="w-6 h-6" strokeWidth={2.5} />
          </button>

          {sheetOpen && (
            <EntryEditorSheet
              // The route already fixed which category the entry belongs to, so
              // the sheet drops its picker instead of offering a way to log the
              // entry somewhere else by accident.
              categories={categories}
              lockedCategory={category}
              onCancel={() => setSheetOpen(false)}
              onSaved={() => {
                setSheetOpen(false);
                reload();
              }}
            />
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
  const baseClass = 'inline-flex items-center justify-center rounded-full border';

  if (!category) {
    return (
      <span
        aria-hidden="true"
        style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
        className={`${baseClass} border-white/5 text-text-disabled opacity-40`}
      >
        <Icon className="w-5 h-5" strokeWidth={2} />
      </span>
    );
  }

  return (
    <Link
      href={categoryHref(category.id)}
      aria-label={`${direction === 'prev' ? 'Previous' : 'Next'} category: ${category.name}`}
      style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
      className={`${baseClass} border-white/10 bg-surface text-text-secondary`}
    >
      <Icon className="w-5 h-5" strokeWidth={2} />
    </Link>
  );
}
