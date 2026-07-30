'use client';
// [review:need-review] PHASE-01/61-today-total-owned-by-hook
// summary: mobile Today screen — same data/handlers as the desktop page via useToday, including the quick-input total and its optimistic increment

import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import AvoidStreakCard from '@/components/AvoidStreakCard';
import QuickNumberRow from '@/components/QuickNumberRow';
import { booleanFields } from '@/lib/today-categories';
import { isFieldChecked, numberFieldSum } from '@/lib/today-entries';
import { TAP_TARGET_PX } from '@/lib/ui-constants';
import { useToday } from '@/hooks/useToday';
import { Check, Sun } from 'lucide-react';

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="text-[12px] font-medium uppercase tracking-widest text-lime truncate">
        {children}
      </span>
      <div className="flex-1 h-px bg-white/5" />
    </div>
  );
}

export default function MobileTodayPage() {
  const {
    date,
    entries,
    groups,
    checked,
    streaks,
    loading,
    error,
    nothingToTrack,
    setError,
    toggleField,
    addNumber,
    reloadStreak,
  } = useToday();

  if (loading) return <LoadingSpinner size="lg" />;

  const {
    avoid: avoidCategories,
    checklist: checklistCategories,
    quickForm: quickFormCategories,
  } = groups;

  return (
    <div className="space-y-6 animate-fade-rise">
      <p className="text-sm text-text-secondary">{date}</p>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {nothingToTrack ? (
        <div className="text-center py-12 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <Sun className="w-7 h-7 text-text-disabled" strokeWidth={2} />
          </div>
          <h2 className="text-base font-medium text-text-primary mb-1">Nothing to track today</h2>
          <p className="text-sm text-text-secondary px-6">
            Create a checklist category or a form category with a number field
          </p>
        </div>
      ) : (
        <>
          {avoidCategories.length > 0 && (
            <section>
              <SectionLabel>Streaks</SectionLabel>
              <div className="space-y-3">
                {avoidCategories.map(({ category, numberField }) => (
                  <AvoidStreakCard
                    key={category.id}
                    category={category}
                    numberField={numberField}
                    streak={streaks[category.id] ?? null}
                    onRelapse={reloadStreak}
                    onError={setError}
                  />
                ))}
              </div>
            </section>
          )}

          {checklistCategories.map((category) => (
            <section key={category.id}>
              <SectionLabel>{category.name}</SectionLabel>
              <div className="grid grid-cols-2 gap-2">
                {booleanFields(category).map((field) => {
                  const isChecked = isFieldChecked(checked, category.id, field.id);
                  return (
                    <button
                      key={field.id}
                      onClick={() => toggleField(category.id, field.id)}
                      aria-pressed={isChecked}
                      style={{ minHeight: TAP_TARGET_PX }}
                      className={`inline-flex items-center justify-center gap-2 px-3 py-3 rounded-2xl text-sm font-medium transition-colors duration-200 border ${
                        isChecked
                          ? 'bg-lime text-background border-lime'
                          : 'bg-card text-text-secondary border-white/10'
                      }`}
                    >
                      {isChecked && <Check className="w-4 h-4 shrink-0" strokeWidth={2.5} />}
                      <span className="truncate">{field.name}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}

          {quickFormCategories.length > 0 && (
            <section>
              <SectionLabel>Quick input</SectionLabel>
              <div className="space-y-3">
                {quickFormCategories.map(({ category, numberField }) => (
                  <QuickNumberRow
                    key={category.id}
                    category={category}
                    numberField={numberField}
                    total={numberFieldSum(entries, category.id, numberField.id)}
                    onAdd={(amount) => addNumber(category.id, numberField.id, amount)}
                  />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
