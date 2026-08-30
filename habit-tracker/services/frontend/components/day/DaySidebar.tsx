'use client';
// [review:need-review] PHASE-03/94
// summary: the day navigation shared by /day/{date} and /life — days grouped year → month with the current month open, each day a square in its three states and a link to that day; one component so the two screens cannot drift apart

import { useState } from 'react';
import Link from 'next/link';
import DaySquare from '@/components/life/DaySquare';
import { useDays } from '@/hooks/useDays';
import { dayStatus, groupByYearAndMonth, monthKeyOf, monthName, toISODate } from '@/lib/life';

/** How far back the sidebar lists days. The history begins in 2026. */
export const SIDEBAR_YEARS = 3;

export const SIDEBAR_TITLE = 'Дни';

/** Shown while the list is empty — an empty box would read as broken. */
export const NO_DAYS_TEXT = 'Дней ещё нет';

export interface DaySidebarProps {
  /** The day the reader is on, so its square is marked and its month opens. */
  activeDate?: string | null;
  /** Pinned in tests; the wall clock everywhere else. */
  today?: Date;
}

/**
 * The list of days, grouped year → month, current month expanded.
 *
 * One component for both screens on purpose. `side.js` was a second navigation
 * that the timeline and the day page each embedded a copy of, and the two drifted
 * until only one of them could tell «не закрыт» from «проигран». Here the grouping,
 * the ordering and the three states are written once.
 */
export default function DaySidebar({ activeDate = null, today = new Date() }: DaySidebarProps) {
  const todayISO = toISODate(today);
  const from = `${today.getFullYear() - SIDEBAR_YEARS}-01-01`;
  const { days, loading, error } = useDays(from, todayISO);

  // The month the reader is in opens; every other one is a heading they click.
  // Which month that is comes from the day they are on, not from the calendar:
  // opening `/day/2026-03-14` and finding August expanded is a navigation that
  // answers a question nobody asked.
  const [open, setOpen] = useState<string | null>(null);
  const openKey = open ?? monthKeyOf(activeDate ?? todayISO);

  const years = groupByYearAndMonth(days);

  return (
    <nav aria-label={SIDEBAR_TITLE} className="space-y-4 text-sm">
      <h2 className="text-text-secondary font-medium">{SIDEBAR_TITLE}</h2>
      {error !== null && <p className="text-text-disabled">{error}</p>}
      {!loading && years.length === 0 && <p className="text-text-disabled">{NO_DAYS_TEXT}</p>}
      {years.map((year) => (
        <div key={year.year} className="space-y-2">
          <p className="text-text-disabled tabular-nums">{year.year}</p>
          {year.months.map((month) => {
            const expanded = month.key === openKey;
            return (
              <div key={month.key}>
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? '' : month.key)}
                  className={`w-full text-left px-2 py-1 rounded-lg transition-colors ${
                    expanded ? 'text-text-primary bg-surface' : 'text-text-secondary hover:text-text-primary'
                  }`}
                >
                  {monthName(month.month)}
                </button>
                {expanded && (
                  <ul className="mt-2 space-y-1 pl-2">
                    {month.days.map((day) => (
                      <li key={day.date} className="flex items-center gap-2">
                        <DaySquare
                          date={day.date}
                          size="sm"
                          status={dayStatus(day, day.date, todayISO)}
                          isToday={day.date === todayISO}
                        />
                        <Link
                          href={`/day/${day.date}`}
                          aria-current={day.date === activeDate ? 'page' : undefined}
                          className={`truncate ${
                            day.date === activeDate
                              ? 'text-lime'
                              : 'text-text-secondary hover:text-text-primary'
                          }`}
                        >
                          {day.date.slice('YYYY-MM-'.length)} {day.title || '—'}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
