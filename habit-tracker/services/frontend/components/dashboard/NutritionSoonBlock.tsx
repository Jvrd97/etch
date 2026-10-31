// [review:need-review] #302
// summary: «Питание · скоро» - a placeholder that holds the place of the nutrition block (ticket #297) so the layout does not move when it arrives; nothing in it is interactive

import { Utensils } from 'lucide-react';
import { DashboardCard } from './DashboardCard';

export function NutritionSoonBlock({ mobile = false }: { mobile?: boolean }) {
  return (
    <DashboardCard title="Питание · скоро" muted mobile={mobile} className="lg:col-span-2">
      <div className="flex items-center gap-4">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-white/5">
          <Utensils className="h-6 w-6 text-text-disabled" strokeWidth={2} aria-hidden="true" />
        </span>
        <p className="text-sm text-text-secondary">
          Калории, белки и рацион появятся здесь позже. Пока блок только держит место.
        </p>
      </div>
    </DashboardCard>
  );
}
