// [review:need-review] PHASE-03/244
// summary: the supplements of the week — taken of planned and the share, each supplement by name with its days, and «данных мало» in place of a share when too few days were planned; a week without supplements draws nothing

import type { HealthAdherence } from '@/lib/api';

export const FEW_DAYS_TEXT = 'Данных мало: добавки планировались меньше трёх дней.';

export default function SupplementsBlock({ adherence }: { adherence: HealthAdherence | null }) {
  if (adherence === null) return null;
  return (
    <section aria-label="Добавки" className="space-y-3">
      <h2 className="text-xl font-semibold text-text-primary">Добавки</h2>
      <div className="bg-card border border-white/5 rounded-3xl p-5 space-y-3">
        <p className="flex flex-wrap items-baseline gap-x-3">
          <span className="text-2xl font-bold text-text-primary">
            {adherence.taken} из {adherence.planned}
          </span>
          {adherence.enough_data && adherence.pct !== null && (
            <span className="text-text-secondary">{adherence.pct}%</span>
          )}
        </p>
        {!adherence.enough_data && <p className="text-sm text-text-secondary">{FEW_DAYS_TEXT}</p>}
        <ul className="space-y-1">
          {adherence.supplements.map((item) => (
            <li key={item.supplement_id} className="flex justify-between gap-3 text-sm">
              <span className="text-text-primary">{item.name}</span>
              <span className="text-text-secondary">
                {item.taken_days} из {item.planned_days} дн.
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
