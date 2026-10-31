// [review:need-review] #302
// summary: the Неделя/Месяц switch of the dashboard - two toggle buttons in one labelled group, pressed state read by screen readers, 44 px targets on the phone

import type { DashboardPeriod } from '@/lib/api';
import { DASHBOARD_PERIODS } from '@/lib/dashboard-summary';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

interface PeriodSwitchProps {
  period: DashboardPeriod;
  onChange: (period: DashboardPeriod) => void;
  mobile?: boolean;
}

export function PeriodSwitch({ period, onChange, mobile = false }: PeriodSwitchProps) {
  return (
    <div
      role="group"
      aria-label="Период сводки"
      className={`rounded-full border border-white/5 bg-surface p-1 ${
        mobile ? 'grid w-full grid-cols-2' : 'inline-flex items-center'
      }`}
    >
      {DASHBOARD_PERIODS.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          aria-pressed={period === id}
          onClick={() => onChange(id)}
          style={mobile ? { minHeight: TAP_TARGET_PX } : undefined}
          className={`rounded-full px-5 py-2 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lime ${
            period === id
              ? 'bg-lime text-background'
              : 'text-text-secondary hover:text-text-primary'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
