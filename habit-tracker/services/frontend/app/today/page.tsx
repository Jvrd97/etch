'use client';
// [review:need-review] PHASE-01/63-today-card-tap-and-visibility, PHASE-03/118, PHASE-03/121, PHASE-03/130
// summary: desktop Today page — markup only; a tap on a quick-input card opens the full entry modal for today's record in that category, and "ask about the day" starts a conversation about the date this screen is showing

import { useState } from 'react';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import AvoidStreakCard from '@/components/AvoidStreakCard';
import QuickMarkRow from '@/components/QuickMarkRow';
import QuickNumberRow from '@/components/QuickNumberRow';
import EntryForm from '@/components/EntryForm';
import AskAboutDayButton from '@/components/chat/AskAboutDayButton';
import { booleanFields } from '@/lib/today-categories';
import { isFieldChecked, numberFieldSum, todayEntryForCategory } from '@/lib/today-entries';
import type { Category } from '@/lib/api';
import { useQuickMarks } from '@/hooks/useQuickMarks';
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
    reload,
  } = useToday();
  // Справочник кнопок отдельным чтением: он живёт дольше дня, и его порядок
  // (плановые впереди, #130) решает сервер, а не этот экран.
  const quickMarks = useQuickMarks();
  // The category whose full editor is open, or null. Held here rather than in
  // the card so only one editor can ever be up.
  const [editing, setEditing] = useState<Category | null>(null);

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

      {/* Рядом с заголовком, а не внизу экрана: разговор идёт про день целиком,
          а не про какую-то одну его карточку. */}
      <AskAboutDayButton date={date} onError={setError} />

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Кнопки справочника (#121) с плановыми впереди (#130). Порядок и
          пометку «в плане» решает сервер: та же выборка обслуживает окно
          агента и iOS, и второй порядок здесь был бы вторым ответом. */}
      {quickMarks.error && (
        <ErrorAlert message={quickMarks.error} onDismiss={quickMarks.reload} />
      )}
      <QuickMarkRow marks={quickMarks.marks} onTap={quickMarks.tap} showHotkeys />

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
                    total={
                      numberField ? numberFieldSum(entries, category.id, numberField.id) : 0
                    }
                    onAdd={(amount) =>
                      numberField
                        ? addNumber(category.id, numberField.id, amount)
                        : Promise.resolve(false)
                    }
                    onOpenEditor={() => setEditing(category)}
                  />
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {editing && (
        <EntryForm
          // Editing today's entry when there is one, creating otherwise: a day
          // of taps should deepen one record, not scatter a dozen.
          entry={todayEntryForCategory(entries, editing.id) ?? null}
          categories={[editing]}
          lockedCategoryId={editing.id}
          date={date}
          onClose={() => setEditing(null)}
          onSuccess={() => {
            setEditing(null);
            void reload();
          }}
        />
      )}
    </div>
  );
}
