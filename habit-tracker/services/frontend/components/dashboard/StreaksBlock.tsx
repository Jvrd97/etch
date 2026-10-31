'use client';
// [review:need-review] #302
// summary: streaks of the window - per category the current and the best length and a row of day dots (filled done, ringed missed, faint unknown) whose meaning is also spelled out for screen readers; the list shows five and opens the rest on request

import Link from 'next/link';
import { useState } from 'react';
import { Flame } from 'lucide-react';
import type { DashboardStreak } from '@/lib/api';
import { streakDaysTally } from '@/lib/dashboard-summary';
import { countable } from '@/lib/plural';
import { MOBILE_PATH_PREFIX } from '@/lib/routes';
import { TAP_TARGET_PX } from '@/lib/ui-constants';
import { DashboardCard, EmptyLine } from './DashboardCard';

/** Streaks shown before «Показать все»; the owner's mockup draws five rows. */
export const STREAKS_COLLAPSED = 5;

function dotsLabel(streak: DashboardStreak): string {
  const { done, missed, unknown } = streakDaysTally(streak.days);
  const doneWord = streak.kind === 'avoid' ? 'без срыва' : 'выполнено';
  const missedWord = streak.kind === 'avoid' ? 'срывов' : 'пропущено';
  return `Последние ${countable(streak.days.length, 'день', 'дня', 'дней')}: ${doneWord} ${done}, ${missedWord} ${missed}, нет данных ${unknown}`;
}

function DayDots({ streak }: { streak: DashboardStreak }) {
  return (
    <span role="img" aria-label={dotsLabel(streak)} className="flex flex-wrap gap-1.5">
      {streak.days.map((day, index) => (
        <span
          key={index}
          aria-hidden="true"
          className={`h-3 w-3 rounded-full ${
            day === true
              ? 'bg-lime'
              : day === false
                ? 'border-2 border-danger'
                : 'bg-white/10'
          }`}
        />
      ))}
    </span>
  );
}

function StreakRow({ streak, mobile }: { streak: DashboardStreak; mobile: boolean }) {
  const href = `${mobile ? MOBILE_PATH_PREFIX : ''}/categories/${streak.category_id}`;
  return (
    <li>
      <Link
        href={href}
        style={mobile ? { minHeight: TAP_TARGET_PX } : undefined}
        className="block rounded-2xl px-2 py-3 transition-colors duration-200 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-lime"
      >
        <span className="flex items-baseline justify-between gap-3">
          <span className="min-w-0 truncate font-medium text-text-primary">
            {streak.name}
            {streak.kind === 'avoid' && (
              <span className="ml-2 rounded-full bg-white/5 px-2 py-0.5 text-[11px] font-normal text-text-secondary">
                без срывов
              </span>
            )}
          </span>
          <span className="flex shrink-0 items-center gap-1.5 text-sm font-semibold text-text-primary">
            <Flame className="h-4 w-4 text-lime" strokeWidth={2} aria-hidden="true" />
            {countable(streak.current, 'день', 'дня', 'дней')}
          </span>
        </span>
        <span className="mt-1 block text-[12px] text-text-secondary">
          лучшая серия {countable(streak.best, 'день', 'дня', 'дней')}
        </span>
        <span className="mt-2 block">
          <DayDots streak={streak} />
        </span>
      </Link>
    </li>
  );
}

interface StreaksBlockProps {
  streaks: DashboardStreak[];
  mobile?: boolean;
}

export function StreaksBlock({ streaks, mobile = false }: StreaksBlockProps) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? streaks : streaks.slice(0, STREAKS_COLLAPSED);
  const hidden = streaks.length - shown.length;
  return (
    <DashboardCard title="Серии" mobile={mobile}>
      {streaks.length === 0 ? (
        <EmptyLine>Серий пока нет: данных мало. Отметьте привычку, и серия начнётся.</EmptyLine>
      ) : (
        <>
          <ul className="-mx-2 divide-y divide-white/5">
            {shown.map((streak) => (
              <StreakRow key={streak.category_id} streak={streak} mobile={mobile} />
            ))}
          </ul>
          {streaks.length > STREAKS_COLLAPSED && (
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => setExpanded((open) => !open)}
              style={mobile ? { minHeight: TAP_TARGET_PX } : undefined}
              className="mt-2 text-sm font-medium text-lime hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lime"
            >
              {expanded ? 'Свернуть' : `Показать все (ещё ${hidden})`}
            </button>
          )}
        </>
      )}
    </DashboardCard>
  );
}
