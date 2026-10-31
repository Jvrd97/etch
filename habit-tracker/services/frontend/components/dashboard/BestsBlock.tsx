// [review:need-review] #302
// summary: the best values of the window (steps, sleep and the like) with the day they happened on and a «Рекорд» mark where the value beats every earlier one

import { Trophy } from 'lucide-react';
import type { DashboardBest, DashboardPeriod } from '@/lib/api';
import { formatDayShort, formatMetricValue } from '@/lib/dashboard-summary';
import { DashboardCard, EmptyLine } from './DashboardCard';

interface BestsBlockProps {
  bests: DashboardBest[];
  period: DashboardPeriod;
  mobile?: boolean;
}

export function BestsBlock({ bests, period, mobile = false }: BestsBlockProps) {
  return (
    <DashboardCard
      title={period === 'week' ? 'Лучшее за неделю' : 'Лучшее за месяц'}
      mobile={mobile}
    >
      {bests.length === 0 ? (
        <EmptyLine>Данных мало: лучшие значения появятся после первых дней записи.</EmptyLine>
      ) : (
        <ul className="divide-y divide-white/5">
          {bests.map((best) => (
            <li key={best.identifier} className="flex items-center justify-between gap-4 py-3">
              <div className="min-w-0">
                <p className="text-[13px] text-text-secondary">{best.label}</p>
                <p className={`font-bold text-text-primary ${mobile ? 'text-xl' : 'text-2xl'}`}>
                  {formatMetricValue(best.value, best.unit)}
                </p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <span className="text-[13px] text-text-secondary">{formatDayShort(best.date)}</span>
                {best.is_record && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-lime/10 px-2.5 py-0.5 text-[12px] font-medium text-lime">
                    <Trophy className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
                    Рекорд
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </DashboardCard>
  );
}
