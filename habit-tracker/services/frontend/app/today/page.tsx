'use client';
// [review:need-review] PHASE-01/61-today-total-owned-by-hook
// summary: desktop Today page — markup only; the quick-input total comes from useToday's entries and the tap goes back to the hook

import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import AvoidStreakCard from '@/components/AvoidStreakCard';
import QuickNumberRow from '@/components/QuickNumberRow';
import { booleanFields } from '@/lib/today-categories';
import { isFieldChecked, numberFieldSum } from '@/lib/today-entries';
import { useToday } from '@/hooks/useToday';
import { Check, Sun } from 'lucide-react';

export default function TodayPage() {
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
    <div className="space-y-8 animate-fade-rise">
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          Today
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">{date} — one tap to check things off</p>
      </div>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {nothingToTrack ? (
        <div className="text-center py-16 bg-card border border-white/5 rounded-3xl">
          <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
            <Sun className="w-8 h-8 text-text-disabled" strokeWidth={2} />
          </div>
          <h3 className="text-lg font-medium text-text-primary mb-1">Nothing to track today</h3>
          <p className="text-text-secondary">
            Create a checklist category or a form category with a number field
          </p>
        </div>
      ) : (
        <>
          {avoidCategories.length > 0 && (
            <section>
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[13px] font-medium uppercase tracking-widest text-lime">
                  Streaks
                </span>
                <div className="flex-1 h-px bg-white/5" />
              </div>
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
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[13px] font-medium uppercase tracking-widest text-lime">
                  {category.name}
                </span>
                <div className="flex-1 h-px bg-white/5" />
              </div>
              <div className="flex flex-wrap gap-3">
                {booleanFields(category).map((field) => {
                  const isChecked = isFieldChecked(checked, category.id, field.id);
                  return (
                    <button
                      key={field.id}
                      onClick={() => toggleField(category.id, field.id)}
                      aria-pressed={isChecked}
                      className={`inline-flex items-center gap-2 px-5 py-3 rounded-full text-sm font-medium transition-all duration-200 border ${
                        isChecked
                          ? 'bg-lime text-background border-lime shadow-[0_0_18px_rgba(184,255,54,0.25)]'
                          : 'bg-card text-text-secondary border-white/10 hover:text-text-primary hover:bg-white/5'
                      }`}
                    >
                      {isChecked && <Check className="w-4 h-4" strokeWidth={2.5} />}
                      {field.name}
                    </button>
                  );
                })}
              </div>
            </section>
          ))}

          {quickFormCategories.length > 0 && (
            <section>
              <div className="flex items-center gap-3 mb-4">
                <span className="text-[13px] font-medium uppercase tracking-widest text-lime">
                  Quick input
                </span>
                <div className="flex-1 h-px bg-white/5" />
              </div>
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
