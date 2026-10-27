'use client';
// [review:need-review] PHASE-03/228
// summary: desktop Today page — the day-mode badge with its switch sits under the title; the badge reads and writes the server's current day, not the browser's date
// [review:need-review] PHASE-01/63-today-card-tap-and-visibility, PHASE-01/201, PHASE-03/118, PHASE-03/121, PHASE-03/122, PHASE-03/130, PHASE-03/123, PHASE-01/177, PHASE-01/206, PHASE-03/237
// summary: desktop Today page — markup only; the quick-mark buttons of the directory come first and take over the categories they cover, a tap on a remaining quick-input card opens the full entry modal for today's record in that category, and the keyboard marks without the mouse while the legend under "?" says which key does what
// summary: desktop Today page — markup only; a tap on a quick-input card opens the full entry modal for today's record in that category, and "ask about the day" starts a conversation about the date this screen is showing
// summary: desktop Today page — a quick-mark card opens the dialog with every set of its category beside the day's records while its plus (and its key) still adds one, and every tap or undo reads the day's records and the streak of its category again
// summary: the date line and the empty-state card follow the server's day: no date line while the day is unknown, no «nothing to track» while a load error is on screen, the day goes to the obligations block

import { useCallback, useState } from 'react';
import QuickMarkSkeleton from '@/components/QuickMarkSkeleton';
import ErrorAlert from '@/components/ErrorAlert';
import AvoidStreakCard from '@/components/AvoidStreakCard';
import ChallengesSection from '@/components/ChallengesSection';
import QuickMarkRow from '@/components/QuickMarkRow';
import QuickMarkDaySets from '@/components/QuickMarkDaySets';
import QuickNumberRow from '@/components/QuickNumberRow';
import TodayDayEntriesList from '@/components/TodayDayEntriesList';
import HotkeyLegend from '@/components/HotkeyLegend';
import EntryForm from '@/components/EntryForm';
import AskAboutDayButton from '@/components/chat/AskAboutDayButton';
import DayModeBadge from '@/components/agent/DayModeBadge';
import { booleanFields } from '@/lib/today-categories';
import { categoriesWithQuickMark } from '@/lib/quick-marks';
import { dayEntriesForCategory, isFieldChecked, numberFieldSum } from '@/lib/today-entries';
import type { Category, Entry } from '@/lib/api';
import { useQuickMarks } from '@/hooks/useQuickMarks';
import { useToday } from '@/hooks/useToday';
import { useTodayList } from '@/hooks/useTodayList';
import { useQuickMarkHotkeys } from '@/hooks/useQuickMarkHotkeys';
import { useDayMode } from '@/hooks/useDayMode';
import { Check, Keyboard, Sun } from 'lucide-react';

export default function TodayPage() {
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
    reloadAfterMark,
  } = useToday();
  // Справочник кнопок отдельным чтением: он живёт дольше дня, и его порядок
  // (плановые впереди, #130) решает сервер, а не этот экран. Кнопки сами
  // перерисовываются из ответа на тап, а записи и серии рядом с ними — чужое
  // состояние, поэтому каждый тап и каждая отмена просят экран перечитать день.
  const quickMarks = useQuickMarks({ onDayChanged: reloadAfterMark });
  // The list a card opened, or none. Held here rather than in the card so only
  // one list can ever be up.
  const dayList = useTodayList(categories, quickMarks.marks);
  const [editing, setEditing] = useState<{ category: Category; entry: Entry | null } | null>(null);
  const [legendOpen, setLegendOpen] = useState(false);
  // Режим дня (#162): бейдж с переключателем. День — тот, что назвал сервер; не вышло прочитать — бейдж говорит об этом и повторяет, день цел.
  const dayMode = useDayMode();

  const markByKey = useCallback((id: number) => void quickMarks.tap(id), [quickMarks]);
  const openLegend = useCallback(() => setLegendOpen(true), []);
  const closeLegend = useCallback(() => setLegendOpen(false), []);

  // The keyboard belongs to this screen alone: the listener lives and dies with
  // it, so the same keys mark nothing on any other route. A modal takes it back
  // for as long as it is up — the legend answers Escape itself, and the entry
  // editor is being typed into.
  useQuickMarkHotkeys({
    marks: quickMarks.marks,
    dialogOpen: legendOpen || editing !== null || dayList.open,
    onMark: markByKey,
    onLegend: openLegend,
  });

  // Каркас, а не спиннер (#123): спиннер закрывает кнопки на всё время
  // круга, а открыли вкладку ради кнопки.
  if (loading) return <QuickMarkSkeleton />;

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
    <>
      <div className="space-y-8 animate-fade-rise">
        <div>
          <h1 className="text-4xl font-bold text-text-primary tracking-tight">
            Today
            <span className="text-lime">.</span>
          </h1>
          {date !== '' && (
            <p className="mt-2 text-text-secondary">{date} — one tap to check things off</p>
          )}
        </div>

        {/* Рядом с заголовком, а не внизу экрана: разговор идёт про день целиком,
            а не про какую-то одну его карточку. */}
        <AskAboutDayButton date={date} onError={setError} />

        <DayModeBadge
          mode={dayMode.mode}
          saving={dayMode.saving}
          reading={dayMode.reading}
          error={dayMode.error}
          loadFailed={dayMode.loadFailed}
          onDecide={(kind, nocode) => void dayMode.decide(kind, nocode)}
          onReset={() => void dayMode.reset()}
          onRetry={() => void dayMode.reload()}
        />

        {error && <ErrorAlert message={error} onDismiss={() => setError(null)} />}

        <ChallengesSection categories={categories} date={date} />

        {nothingToTrack && error === null ? (
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
            {quickMarks.marks.length > 0 && (
              <section>
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-[13px] font-medium uppercase tracking-widest text-lime">
                    Быстрые отметки
                  </span>
                  <div className="flex-1 h-px bg-white/5" />
                  <button
                    type="button"
                    onClick={openLegend}
                    aria-label="Клавиши быстрых отметок"
                    className="inline-flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors duration-200"
                  >
                    <Keyboard className="w-4 h-4" strokeWidth={2} />
                    <kbd className="px-1.5 py-0.5 rounded-md border border-white/15 text-[10px] leading-none">
                      ?
                    </kbd>
                  </button>
                </div>
                <QuickMarkRow
                  marks={quickMarks.marks}
                  onTap={markByKey}
                  onOpen={dayList.openMark}
                  lastEvent={quickMarks.lastEvent}
                  onUndo={() => void quickMarks.undo()}
                  showHotkeys
                />
              </section>
            )}

            {avoidCategories.length > 0 && (
              <section>
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-[13px] font-medium uppercase tracking-widest text-lime">
                    Streaks
                  </span>
                  <div className="flex-1 h-px bg-white/5" />
                </div>
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
                      onOpenEntries={() => dayList.openCategory(category)}
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
                  <button type="button" onClick={() => dayList.openCategory(category)} className="text-sm text-text-secondary hover:text-text-primary">Записи</button>
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
                      onOpenEditor={() => dayList.openCategory(category)}
                    />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>

      {/* Outside the animated column on purpose. The column ends its entrance on
          a transform, and a transformed ancestor becomes the containing block of
          every fixed descendant: a dialog inside it is centred in the column and
          dims only the column, not the screen. */}
      {legendOpen && <HotkeyLegend marks={quickMarks.marks} onClose={closeLegend} />}

      {dayList.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          {/* The title bar stays put and the lists scroll under it: twenty sets
              are taller than the dialog, and a Close button that scrolls away
              with them is a dialog with no visible way out. */}
          <section aria-label={dayList.title} className="flex max-h-full w-full max-w-xl flex-col gap-4 rounded-3xl border border-white/10 bg-card p-6">
            <div className="flex shrink-0 items-center justify-between gap-3">
              <h2 className="text-xl font-semibold text-text-primary">{dayList.title}</h2>
              <button type="button" onClick={dayList.close} aria-label="Close" className="rounded-xl px-3 py-2 text-text-secondary hover:text-text-primary">Закрыть</button>
            </div>
            <div className="min-h-0 flex-1 space-y-5 overflow-y-auto">
              {dayList.mark && (
                <QuickMarkDaySets mark={dayList.mark} onUndo={quickMarks.undoEvent} />
              )}
              {dayList.category && (
                <TodayDayEntriesList
                  category={dayList.category}
                  entries={dayEntriesForCategory(entries, dayList.category.id)}
                  heading={dayList.mark ? 'Записи за день' : undefined}
                  onEdit={(entry) => {
                    const category = dayList.category;
                    dayList.close();
                    if (category) setEditing({ category, entry });
                  }}
                  onDelete={deleteEntry}
                  onAdd={() => {
                    const category = dayList.category;
                    dayList.close();
                    if (category) setEditing({ category, entry: null });
                  }}
                />
              )}
            </div>
          </section>
        </div>
      )}

      {editing && (
        <EntryForm
          entry={editing.entry}
          categories={[editing.category]}
          lockedCategoryId={editing.category.id}
          date={date}
          onUpdateExisting={updateEntry}
          onClose={() => setEditing(null)}
          onSuccess={() => {
            setEditing(null);
            void reload();
          }}
        />
      )}
    </>
  );
}
