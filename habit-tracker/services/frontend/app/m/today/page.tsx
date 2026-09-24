'use client';
// [review:need-review] PHASE-01/84-voice-day-input, PHASE-01/201, PHASE-03/118, PHASE-03/121, PHASE-03/123, PHASE-01/177
// summary: mobile Today screen — the quick-mark buttons of the directory come first and take over the categories they cover, a tap on a remaining quick-input card opens the full-screen entry editor, and the button above the sections opens the dictation sheet that fills the whole day in at once
// summary: mobile Today screen — a tap on a quick-input card opens the full-screen entry editor, the button above the sections opens the dictation sheet that fills the whole day in at once, and the one beside it starts a conversation about the date this screen is showing

import { useState } from 'react';
import QuickMarkSkeleton from '@/components/QuickMarkSkeleton';
import ErrorAlert from '@/components/ErrorAlert';
import AvoidStreakCard from '@/components/AvoidStreakCard';
import ChallengesSection from '@/components/ChallengesSection';
import QuickMarkRow from '@/components/QuickMarkRow';
import QuickNumberRow from '@/components/QuickNumberRow';
import TodayDayEntriesList from '@/components/TodayDayEntriesList';
import EntryEditorSheet from '@/components/mobile/EntryEditorSheet';
import FullScreenSheet from '@/components/mobile/FullScreenSheet';
import VoiceDaySheet from '@/components/mobile/VoiceDaySheet';
import AskAboutDayButton from '@/components/chat/AskAboutDayButton';
import { booleanFields } from '@/lib/today-categories';
import { categoriesWithQuickMark } from '@/lib/quick-marks';
import { dayEntriesForCategory, isFieldChecked, numberFieldSum } from '@/lib/today-entries';
import type { Category, Entry } from '@/lib/api';
import { TAP_TARGET_PX, TELL_DAY_LABEL } from '@/lib/ui-constants';
import { useQuickMarks } from '@/hooks/useQuickMarks';
import { useToday } from '@/hooks/useToday';
import { Check, Mic, Sun } from 'lucide-react';

/**
 * Accessible name of the control that opens the dictation sheet.
 *
 * Exported because the test asserts on it, and named exports out of an App
 * Router `page.tsx` are otherwise a contract Next does not promise to keep.
 */

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
    categories,
    groups,
    checked,
    streaks,
    loading,
    streaksError,
    error,
    nothingToTrack,
    setError,
    toggleField,
    addNumber,
    updateEntry,
    deleteEntry,
    reloadStreak,
    reload,
  } = useToday();
  // Справочник кнопок отдельным чтением: он живёт дольше дня, и его порядок
  // (плановые впереди, #130) решает сервер, а не этот экран.
  const quickMarks = useQuickMarks();
  // The category whose full editor is open, or null. Held here rather than in
  // the card so only one sheet can ever be up.
  const [listCategory, setListCategory] = useState<Category | null>(null);
  const [editing, setEditing] = useState<{ category: Category; entry: Entry | null } | null>(null);
  const [dictating, setDictating] = useState(false);

  // Каркас, а не спиннер (#123): спиннер закрывает кнопки на всё время
  // круга, а открыли вкладку ради кнопки.
  if (loading) return <QuickMarkSkeleton compact />;

  const {
    avoid: avoidCategories,
    checklist: checklistCategories,
    quickForm: allQuickFormCategories,
  } = groups;
  // A category the directory already answers for loses its legacy card: two
  // ways to add to the same field on one screen is one too many. An empty
  // directory covers nothing, so the screen stays exactly as it was.
  const covered = categoriesWithQuickMark(quickMarks.marks);
  const quickFormCategories = allQuickFormCategories.filter(
    ({ category }) => !covered.has(category.id)
  );

  return (
    <div className="space-y-6 animate-fade-rise">
      <p className="text-sm text-text-secondary">{date}</p>

      {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

      <ChallengesSection categories={categories} />

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

      {/* Под диктовкой и на всю ширину, как она: оба действия — про день
          целиком, и оба открываются одним большим касанием. */}
      <AskAboutDayButton date={date} onError={setError} className="w-full" />

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
          {quickMarks.marks.length > 0 && (
            <section>
              <SectionLabel>Быстрые отметки</SectionLabel>
              <QuickMarkRow
                marks={quickMarks.marks}
                onTap={(id) => void quickMarks.tap(id)}
                lastEvent={quickMarks.lastEvent}
                onUndo={() => void quickMarks.undo()}
              />
            </section>
          )}

          {avoidCategories.length > 0 && (
            <section>
              <SectionLabel>Streaks</SectionLabel>
              {streaksError !== null && (
                // Внутри секции, а не баннером над экраном: упали цифры дней,
                // а не кнопки, и убирать из-за них рабочий экран нечестно.
                <p role="status" className="text-xs text-text-secondary mb-3">
                  {streaksError}
                </p>
              )}
              <div className="space-y-3">
                {avoidCategories.map(({ category, numberField }) => (
                  <AvoidStreakCard
                    key={category.id}
                    category={category}
                    numberField={numberField}
                    entries={entries}
                    streak={streaks[category.id] ?? null}
                    onRelapse={reloadStreak}
                    onEntriesChanged={reload}
                    onError={setError}
                    onOpenEntries={() => setListCategory(category)}
                  />
                ))}
              </div>
            </section>
          )}

          {checklistCategories.map((category) => (
            <section key={category.id}>
              <div className="mb-3 flex items-center justify-between gap-3">
                <SectionLabel>{category.name}</SectionLabel>
                <button type="button" onClick={() => setListCategory(category)} className="text-sm text-text-secondary">Записи</button>
              </div>
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
                    onOpenEditor={() => setListCategory(category)}
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

      {listCategory && (
        <FullScreenSheet
          title={`${listCategory.name} — сегодня`}
          onCancel={() => setListCategory(null)}
          onDone={() => {
            setEditing({ category: listCategory, entry: null });
            setListCategory(null);
          }}
          doneLabel="Добавить"
        >
          <TodayDayEntriesList
            category={listCategory}
            entries={dayEntriesForCategory(entries, listCategory.id)}
            onEdit={(entry) => {
              setEditing({ category: listCategory, entry });
              setListCategory(null);
            }}
            onDelete={deleteEntry}
            onAdd={() => {
              setEditing({ category: listCategory, entry: null });
              setListCategory(null);
            }}
          />
        </FullScreenSheet>
      )}

      {editing && (
        <EntryEditorSheet
          entry={editing.entry}
          categories={[editing.category]}
          lockedCategory={editing.category}
          onUpdateExisting={updateEntry}
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
