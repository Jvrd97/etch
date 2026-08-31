'use client';
// [review:need-review] PHASE-03/152
// summary: /settings/day-rules — точка входа десктопной оболочки; сам экран правил живёт в components/settings, потому что страница только называет его

import DayRulesScreen from '@/components/settings/DayRulesScreen';

export default function DayRulesPage() {
  return <DayRulesScreen />;
}
