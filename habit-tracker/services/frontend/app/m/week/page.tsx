'use client';
// [review:need-review] PHASE-03/94
// summary: /m/week — mobile entry point; the current week on the mobile type scale

import WeekScreen from '@/components/week/WeekScreen';

export default function MobileCurrentWeekPage() {
  return <WeekScreen iso={null} compact />;
}
