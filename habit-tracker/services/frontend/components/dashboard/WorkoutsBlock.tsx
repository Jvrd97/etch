// [review:need-review] #302
// summary: workouts per week as bars scaled to the busiest week, the total and the change against the previous period; every bar carries its count and minutes as text, an empty week stays a flat line

import { Dumbbell } from 'lucide-react';
import type { DashboardWorkouts } from '@/lib/api';
import { MINUS, formatDayShort, formatMinutes, workoutBarFractions } from '@/lib/dashboard-summary';
import { countable } from '@/lib/plural';
import { DashboardCard, EmptyLine } from './DashboardCard';

const BAR_AREA_PX = 96;
const MIN_BAR_PX = 3;

function deltaText(delta: number | null): string | null {
  if (delta === null) return null;
  if (delta === 0) return 'столько же, сколько в прошлом периоде';
  return `${delta > 0 ? '+' : MINUS}${Math.abs(delta)} к прошлому периоду`;
}

interface WorkoutsBlockProps {
  workouts: DashboardWorkouts | null;
  mobile?: boolean;
}

export function WorkoutsBlock({ workouts, mobile = false }: WorkoutsBlockProps) {
  const empty = workouts === null || workouts.weeks.length === 0;
  const fractions = empty ? [] : workoutBarFractions(workouts.weeks);
  const change = empty ? null : deltaText(workouts.delta_vs_previous);
  return (
    <DashboardCard
      title="Динамика тренировок"
      aside={
        empty ? undefined : (
          <>
            всего {workouts.total}
            {change !== null && <span className="ml-2">{change}</span>}
          </>
        )
      }
      mobile={mobile}
    >
      {empty ? (
        <EmptyLine>Данных мало: тренировок в этом окне не записано.</EmptyLine>
      ) : (
        <ol aria-label="Тренировки по неделям" className="flex items-end gap-3">
          {workouts.weeks.map((week, index) => (
            <li
              key={week.week_start}
              className="flex min-w-0 flex-1 flex-col items-center gap-1 text-center"
            >
              <span className="flex items-center gap-1 text-sm font-semibold text-text-primary">
                <Dumbbell className="h-3.5 w-3.5 text-lime" strokeWidth={2} aria-hidden="true" />
                <span aria-hidden="true">{week.count}</span>
                <span className="sr-only">
                  {`Неделя с ${formatDayShort(week.week_start)}: ${countable(week.count, 'тренировка', 'тренировки', 'тренировок')}, ${formatMinutes(week.minutes)}`}
                </span>
              </span>
              <span
                aria-hidden="true"
                className="flex w-full items-end justify-center"
                style={{ height: BAR_AREA_PX }}
              >
                <span
                  className="w-full max-w-10 rounded-t-lg bg-lime"
                  style={{ height: Math.max(MIN_BAR_PX, Math.round(fractions[index] * BAR_AREA_PX)) }}
                />
              </span>
              <span aria-hidden="true" className="text-[12px] text-text-secondary">
                {formatDayShort(week.week_start)}
              </span>
              <span aria-hidden="true" className="text-[11px] text-text-disabled">
                {formatMinutes(week.minutes)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </DashboardCard>
  );
}
