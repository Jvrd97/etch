'use client';
// [review:need-review] PHASE-01/84-voice-day-input, PHASE-03/121
// summary: mobile Today screen — the quick-mark buttons of the directory come first and take over the categories they cover, a tap on a remaining quick-input card opens the full-screen entry editor, and the button above the sections opens the dictation sheet that fills the whole day in at once

import { useState } from 'react';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import AvoidStreakCard from '@/components/AvoidStreakCard';
import QuickNumberRow from '@/components/QuickNumberRow';
import QuickMarkRow from '@/components/QuickMarkRow';
import EntryEditorSheet from '@/components/mobile/EntryEditorSheet';
import VoiceDaySheet from '@/components/mobile/VoiceDaySheet';
import { booleanFields } from '@/lib/today-categories';
import { categoriesWithQuickMark } from '@/lib/quick-marks';
import { isFieldChecked, numberFieldSum, todayEntryForCategory } from '@/lib/today-entries';
import type { Category } from '@/lib/api';
import { TAP_TARGET_PX } from '@/lib/ui-constants';
import { useToday } from '@/hooks/useToday';
import { Check, Mic, Sun } from 'lucide-react';

/**
 * Accessible name of the control that opens the dictation sheet.
 *
 * Exported because the test asserts on it, and named exports out of an App
 * Router `page.tsx` are otherwise a contract Next does not promise to keep.
 */
export const TELL_DAY_LABEL = 'Рассказать день голосом';

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
    quickMarks,
    checked,
    streaks,
    loading,
    error,
    nothingToTrack,
    setError,
    toggleField,
    addNumber,
    tapQuickMark,
    lastQuickMarkEvent,
    undoLastQuickMark,
    reloadStreak,
    reload,
  } = useToday();
  // The category whose full editor is open, or null. Held here rather than in
  // the card so only one sheet can ever be up.
  const [editing, setEditing] = useState<Category | null>(null);
  const [dictating, setDictating] = useState(false);

  if (loading) return <LoadingSpinner size="lg" />;

  const {
    avoid: avoidCategories,
    checklist: checklistCategories,
    quickForm: allQuickFormCategories,
  } = groups;
  // A category the directory already answers for loses its legacy card: two
  // ways to add to the same field on one screen is one too many. An empty
  // directory covers nothing, so the screen stays exactly as it was.
  const covered = categoriesWithQuickMark(quickMarks);
  const quickFormCategories = allQuickFormCategories.filter(
    ({ category }) => !covered.has(category.id)
  );

  return (
    <div className="space-y-6 animate-fade-rise">
      <p className="text-sm text-text-secondary">{date}</p>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      {/* Above the sections rather than beside one of them: dictation fills in
          the whole day — several categories, the checklist and the day's text
          together — so it belongs to the screen, not to any card on it. It
          stays offered even when there is nothing to track yet, because a
          spoken day is also the fastest way to find out what is missing. */}
      <button
        type="button"
        onClick={() => setDictating(true)}
        aria-label={TELL_DAY_LABEL}
        style={{ minHeight: TAP_TARGET_PX }}
        className="w-full inline-flex items-center justify-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-transform duration-200 active:scale-95"
      >
        <Mic className="w-4 h-4 shrink-0" strokeWidth={2} />
        Рассказать день
      </button>

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
          {quickMarks.length > 0 && (
            <section>
              <SectionLabel>Быстрые отметки</SectionLabel>
              <QuickMarkRow
                marks={quickMarks}
                onTap={(id) => void tapQuickMark(id)}
                lastEvent={lastQuickMarkEvent}
                onUndo={() => void undoLastQuickMark()}
              />
            </section>
          )}

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

      {dictating && (
        <VoiceDaySheet
          onClose={() => setDictating(false)}
          // A dictated day lands in the very categories this screen is
          // showing, so the sheet closing onto stale totals is how the same
          // lunch gets logged twice.
          onApplied={() => {
            setDictating(false);
            void reload();
          }}
        />
      )}

      {editing && (
        <EntryEditorSheet
          // Editing today's entry when there is one, creating otherwise: a day
          // of taps should deepen one record, not scatter a dozen.
          entry={todayEntryForCategory(entries, editing.id) ?? null}
          categories={[editing]}
          lockedCategory={editing}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      )}
    </div>
  );
}
