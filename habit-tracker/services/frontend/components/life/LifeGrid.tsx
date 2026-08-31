'use client';
// [review:need-review] PHASE-03/94, PHASE-03/144
// summary: the /life timeline — five views (жизнь → год → месяц → неделя → день) over one range of days, the weeks-lived/weeks-left counter life.html showed, squares in three readable states that link to /day/{date}, the note saying whether the day's verdict was computed or carried over from a record, and a way through to the week page

import { useMemo, useState } from 'react';
import Link from 'next/link';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import DaySquare, { DaySquareLegend } from '@/components/life/DaySquare';
import { useDays } from '@/hooks/useDays';
import { verdictOriginLabel } from '@/lib/day-format';
import { type DayListItem } from '@/lib/api';
import {
  DEFAULT_BIRTH,
  DEFAULT_TARGET_YEARS,
  WEEKDAY_SHORT,
  WEEKS_PER_ROW,
  addDays,
  dayStatus,
  daysByDate,
  fromISODate,
  isoWeekCode,
  lifeCounter,
  monthDates,
  monthName,
  startOfWeek,
  toISODate,
} from '@/lib/life';

/** The five views, in the order the ticket names them. */
export const VIEWS = ['life', 'year', 'month', 'week', 'day'] as const;
export type LifeView = (typeof VIEWS)[number];

export const VIEW_LABEL: Record<LifeView, string> = {
  life: 'жизнь',
  year: 'год',
  month: 'месяц',
  week: 'неделя',
  day: 'день',
};

/**
 * How far back the timeline asks the API for days.
 *
 * The squares of a life grid span decades, and the recorded history spans one
 * year: fetching decades of empty dates would be a range the server refuses.
 * Anything outside this window is drawn from the calendar alone — `future`
 * ahead of today, `empty` behind it — which is what those dates are.
 */
export const HISTORY_YEARS = 3;

/** localStorage key of the frame: the birth date and how many years to draw. */
export const LIFE_FRAME_KEY = 'habit-tracker:life-frame';

const MONTHS_IN_YEAR = 12;

interface Frame {
  birth: string;
  targetYears: number;
}

/** The frame from localStorage, or the defaults `life.html` shipped with. */
function readFrame(): Frame {
  const fallback = { birth: DEFAULT_BIRTH, targetYears: DEFAULT_TARGET_YEARS };
  if (typeof window === 'undefined') return fallback;
  try {
    const stored = window.localStorage.getItem(LIFE_FRAME_KEY);
    if (stored === null) return fallback;
    const parsed: unknown = JSON.parse(stored);
    if (typeof parsed !== 'object' || parsed === null) return fallback;
    const { birth, targetYears } = parsed as Partial<Frame>;
    return {
      birth: typeof birth === 'string' ? birth : fallback.birth,
      targetYears: typeof targetYears === 'number' ? targetYears : fallback.targetYears,
    };
  } catch {
    // A corrupted value is not worth a broken page; the defaults are the ones
    // the old page used, so nothing about the counter changes silently.
    return fallback;
  }
}

function writeFrame(frame: Frame): void {
  try {
    window.localStorage.setItem(LIFE_FRAME_KEY, JSON.stringify(frame));
  } catch {
    // Private mode, storage disabled — the frame stays in memory for this
    // session rather than the page failing to render.
  }
}

export interface LifeGridProps {
  /** Pinned in tests; the wall clock everywhere else. */
  today?: Date;
  /** Tighter type scale for the mobile shell. */
  compact?: boolean;
}

export default function LifeGrid({ today = new Date(), compact = false }: LifeGridProps) {
  const [view, setView] = useState<LifeView>('life');
  const [cursor, setCursor] = useState<Date>(() => new Date(today));
  const [frame, setFrame] = useState<Frame>(() => readFrame());

  const todayISO = toISODate(today);
  const from = `${today.getFullYear() - HISTORY_YEARS}-01-01`;
  const to = `${today.getFullYear()}-12-31`;
  const { days, loading, error, reload } = useDays(from, to);

  const byDate = useMemo(() => daysByDate(days), [days]);
  const counter = useMemo(
    () => lifeCounter(frame.birth, frame.targetYears, today),
    [frame, today]
  );

  const go = (next: LifeView, at?: Date) => {
    if (at !== undefined) setCursor(at);
    setView(next);
  };

  const square = (date: Date, size: 'sm' | 'md' | 'lg') => {
    const iso = toISODate(date);
    const day = byDate.get(iso);
    return (
      <DaySquare
        key={iso}
        date={iso}
        size={size}
        status={dayStatus(day, iso, todayISO)}
        detail={detailOf(day)}
        isToday={iso === todayISO}
      />
    );
  };

  return (
    <div className="space-y-8 animate-fade-rise">
      <header>
        <h1
          className={`${compact ? 'text-2xl' : 'text-4xl'} font-bold text-text-primary tracking-tight`}
        >
          Жизнь<span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">
          Один квадрат — один день. Заполненный лаймом — выигран, заполненный серым —
          проигран, пустой контур — не закрыт.
        </p>
      </header>

      <LifeCounterBlock counter={counter} frame={frame} onChange={(next) => {
        setFrame(next);
        writeFrame(next);
      }} />

      <nav className="flex flex-wrap gap-2" aria-label="Вид таймлайна">
        {VIEWS.map((candidate) => (
          <button
            key={candidate}
            type="button"
            onClick={() => go(candidate)}
            aria-pressed={view === candidate}
            className={`px-4 py-2 rounded-full text-sm font-medium transition-colors ${
              view === candidate
                ? 'bg-lime text-background'
                : 'bg-surface text-text-secondary hover:text-text-primary'
            }`}
          >
            {VIEW_LABEL[candidate]}
          </button>
        ))}
      </nav>

      {error !== null && <ErrorAlert message={error} onDismiss={() => reload()} />}
      {loading ? (
        <LoadingSpinner size="lg" />
      ) : (
        <section aria-label={`Вид: ${VIEW_LABEL[view]}`}>
          {view === 'life' && (
            <LifeView
              birth={frame.birth}
              targetYears={frame.targetYears}
              today={today}
              byDate={byDate}
              todayISO={todayISO}
              onPickWeek={(monday) => go('week', monday)}
            />
          )}
          {view === 'year' && (
            <YearView
              cursor={cursor}
              square={square}
              onPickMonth={(first) => go('month', first)}
              onStep={(years) =>
                setCursor(new Date(cursor.getFullYear() + years, cursor.getMonth(), 1))
              }
            />
          )}
          {view === 'month' && (
            <MonthView
              cursor={cursor}
              square={square}
              onPickWeek={(monday) => go('week', monday)}
              onStep={(months) =>
                setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + months, 1))
              }
            />
          )}
          {view === 'week' && (
            <WeekView
              cursor={cursor}
              square={square}
              byDate={byDate}
              onPickDay={(date) => go('day', date)}
              onStep={(weeks) => setCursor(addDays(cursor, weeks * WEEKDAY_SHORT.length))}
            />
          )}
          {view === 'day' && <DayView cursor={cursor} byDate={byDate} />}
        </section>
      )}

      <DaySquareLegend />
    </div>
  );
}

/** The tooltip tail: the title of the plan and how its tasks went. */
function detailOf(day: DayListItem | undefined): string | undefined {
  if (day === undefined) return undefined;
  const counts = day.total > 0 ? `задачи ${day.done} из ${day.total}` : undefined;
  return [day.title, counts].filter((part) => part).join(' · ') || undefined;
}

interface CounterProps {
  counter: ReturnType<typeof lifeCounter>;
  frame: Frame;
  onChange: (frame: Frame) => void;
}

/** The block above the grid — the same six numbers `life.html` showed. */
function LifeCounterBlock({ counter, frame, onChange }: CounterProps) {
  return (
    <div className="bg-card border border-white/5 rounded-3xl p-6 space-y-4">
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <dt className="text-sm text-text-secondary">Возраст</dt>
          <dd className="text-2xl font-bold text-text-primary">{counter.years}</dd>
        </div>
        <div>
          <dt className="text-sm text-text-secondary">Прожито недель</dt>
          <dd className="text-2xl font-bold text-text-primary">
            {counter.weeksLived}
            <span className="text-sm text-text-secondary"> из {counter.weeksTotal}</span>
          </dd>
        </div>
        <div>
          <dt className="text-sm text-text-secondary">Осталось недель</dt>
          <dd className="text-2xl font-bold text-lime">{counter.weeksLeft}</dd>
        </div>
        <div>
          <dt className="text-sm text-text-secondary">Прожито</dt>
          <dd className="text-2xl font-bold text-text-primary">
            {counter.percent.toFixed(1)}%
          </dd>
        </div>
      </dl>
      <div className="h-1.5 rounded-full bg-surface overflow-hidden">
        <div className="h-full bg-lime" style={{ width: `${counter.percent}%` }} />
      </div>
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="inline-flex items-center gap-2 text-text-secondary">
          Дата рождения
          <input
            type="date"
            value={frame.birth}
            onChange={(event) => onChange({ ...frame, birth: event.target.value })}
            className="bg-surface rounded-lg px-2 py-1 text-text-primary"
          />
        </label>
        <label className="inline-flex items-center gap-2 text-text-secondary">
          Рамка, лет
          <input
            type="number"
            min={1}
            max={120}
            value={frame.targetYears}
            onChange={(event) =>
              onChange({ ...frame, targetYears: Number(event.target.value) })
            }
            className="bg-surface rounded-lg px-2 py-1 w-20 text-text-primary"
          />
        </label>
      </div>
      <p className="text-sm text-text-disabled">
        Рамка — не прогноз, а линейка: она нужна, чтобы видеть масштаб, а не чтобы знать
        дату.
      </p>
    </div>
  );
}

interface LifeViewProps {
  birth: string;
  targetYears: number;
  today: Date;
  byDate: Map<string, DayListItem>;
  todayISO: string;
  onPickWeek: (monday: Date) => void;
}

/** One row per year of life, one cell per week — the grid `life.html` opened on. */
function LifeView({ birth, targetYears, today, byDate, todayISO, onPickWeek }: LifeViewProps) {
  const firstWeek = startOfWeek(fromISODate(birth));
  const currentWeek = startOfWeek(today).getTime();
  const rows = [];
  for (let year = 0; year < targetYears; year += 1) {
    const cells = [];
    for (let week = 0; week < WEEKS_PER_ROW; week += 1) {
      const start = addDays(firstWeek, (year * WEEKS_PER_ROW + week) * WEEKDAY_SHORT.length);
      const iso = toISODate(start);
      // The week is won when any of its days was, and lost when any was and
      // none was won: one square cannot say seven things, and «была ли победа»
      // is the question the life view is looking at.
      let won = 0;
      let lost = 0;
      let open = 0;
      for (let offset = 0; offset < WEEKDAY_SHORT.length; offset += 1) {
        const date = toISODate(addDays(start, offset));
        const status = dayStatus(byDate.get(date), date, todayISO);
        if (status === 'won') won += 1;
        else if (status === 'lost') lost += 1;
        else if (status === 'open') open += 1;
      }
      const status =
        won > 0 ? 'won' : lost > 0 ? 'lost' : open > 0 ? 'open' : start > today ? 'future' : 'empty';
      cells.push(
        <button
          key={iso}
          type="button"
          onClick={() => onPickWeek(start)}
          title={`${isoWeekCode(start)} · выиграно ${won}, проиграно ${lost}`}
          aria-label={`Неделя ${isoWeekCode(start)}`}
          data-week={iso}
          data-status={status}
          className={`w-2 h-2 rounded-[2px] border ${
            status === 'won'
              ? 'bg-lime border-lime'
              : status === 'lost'
                ? 'bg-text-disabled border-text-disabled'
                : status === 'open'
                  ? 'bg-transparent border-lime'
                  : status === 'empty'
                    ? 'bg-white/5 border-white/5'
                    : 'bg-transparent border-white/10'
          } ${start.getTime() === currentWeek ? 'ring-1 ring-white/70' : ''}`}
        />
      );
    }
    rows.push(
      <div key={year} className="flex items-center gap-1">
        <span className="w-6 text-right text-[10px] text-text-disabled tabular-nums">
          {year}
        </span>
        <div className="flex gap-[2px]">{cells}</div>
      </div>
    );
  }
  return <div className="space-y-[2px] overflow-x-auto">{rows}</div>;
}

interface StepProps {
  title: string;
  onStep: (delta: number) => void;
}

/** Previous / next of whatever the current view is looking at. */
function Stepper({ title, onStep }: StepProps) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <button
        type="button"
        onClick={() => onStep(-1)}
        aria-label="Назад"
        className="px-3 py-1 rounded-full bg-surface text-text-secondary hover:text-text-primary"
      >
        ←
      </button>
      <h2 className="text-xl font-semibold text-text-primary">{title}</h2>
      <button
        type="button"
        onClick={() => onStep(1)}
        aria-label="Вперёд"
        className="px-3 py-1 rounded-full bg-surface text-text-secondary hover:text-text-primary"
      >
        →
      </button>
    </div>
  );
}

type SquareFn = (date: Date, size: 'sm' | 'md' | 'lg') => React.ReactNode;

function YearView({
  cursor,
  square,
  onPickMonth,
  onStep,
}: {
  cursor: Date;
  square: SquareFn;
  onPickMonth: (first: Date) => void;
  onStep: (years: number) => void;
}) {
  return (
    <div>
      <Stepper title={String(cursor.getFullYear())} onStep={onStep} />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
        {Array.from({ length: MONTHS_IN_YEAR }, (_, index) => {
          const first = new Date(cursor.getFullYear(), index, 1);
          return (
            <div key={index} className="bg-card border border-white/5 rounded-2xl p-4">
              <button
                type="button"
                onClick={() => onPickMonth(first)}
                className="text-sm text-text-secondary hover:text-lime mb-3"
              >
                {monthName(index + 1)}
              </button>
              <div className="flex flex-wrap gap-1">
                {monthDates(first).map((date) => square(date, 'sm'))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MonthView({
  cursor,
  square,
  onPickWeek,
  onStep,
}: {
  cursor: Date;
  square: SquareFn;
  onPickWeek: (monday: Date) => void;
  onStep: (months: number) => void;
}) {
  const dates = monthDates(cursor);
  const weeks = new Map<string, Date[]>();
  for (const date of dates) {
    const key = toISODate(startOfWeek(date));
    weeks.set(key, [...(weeks.get(key) ?? []), date]);
  }
  return (
    <div>
      <Stepper
        title={`${monthName(cursor.getMonth() + 1)} ${cursor.getFullYear()}`}
        onStep={onStep}
      />
      <div className="space-y-2">
        {[...weeks.entries()].map(([key, dayDates]) => (
          <div key={key} className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => onPickWeek(fromISODate(key))}
              className="w-20 text-left text-xs text-text-disabled hover:text-lime"
            >
              {isoWeekCode(fromISODate(key))}
            </button>
            <div className="flex gap-1">{dayDates.map((date) => square(date, 'md'))}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function WeekView({
  cursor,
  square,
  byDate,
  onPickDay,
  onStep,
}: {
  cursor: Date;
  square: SquareFn;
  byDate: Map<string, DayListItem>;
  onPickDay: (date: Date) => void;
  onStep: (weeks: number) => void;
}) {
  const monday = startOfWeek(cursor);
  const iso = isoWeekCode(monday);
  return (
    <div>
      <Stepper title={iso} onStep={onStep} />
      <Link href={`/week/${iso}`} className="text-sm text-lime hover:underline">
        Открыть неделю {iso} с ретро →
      </Link>
      <div className="mt-4 grid grid-cols-7 gap-3">
        {WEEKDAY_SHORT.map((name, index) => {
          const date = addDays(monday, index);
          const day = byDate.get(toISODate(date));
          return (
            <div key={name} className="bg-card border border-white/5 rounded-2xl p-3 space-y-2">
              <button
                type="button"
                onClick={() => onPickDay(date)}
                className="text-xs text-text-disabled hover:text-lime"
              >
                {name} {date.getDate()}
              </button>
              {square(date, 'lg')}
              <p className="text-xs text-text-secondary line-clamp-2">
                {day?.title || '—'}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DayView({ cursor, byDate }: { cursor: Date; byDate: Map<string, DayListItem> }) {
  const iso = toISODate(cursor);
  const day = byDate.get(iso);
  return (
    <div className="bg-card border border-white/5 rounded-3xl p-6 space-y-3">
      <h2 className="text-2xl font-bold text-text-primary">{iso}</h2>
      <p className="text-text-secondary">{day?.title || 'Плана нет'}</p>
      <p className="text-text-secondary">
        {day === undefined
          ? 'Записи об этом дне нет.'
          : `Задачи ${day.done} из ${day.total}. ${
              day.verdict === null
                ? 'День не закрыт.'
                : `Вердикт: ${day.verdict} (${verdictOriginLabel(day.verdict_origin)}).`
            }`}
      </p>
      <Link href={`/day/${iso}`} className="inline-block text-lime hover:underline">
        Открыть день {iso} →
      </Link>
    </div>
  );
}
