'use client';
// [review:need-review] PHASE-03/94
// summary: /week — the entry point from the navigation; the week is left unnamed so the server answers with the current one by its own day boundary, not by the browser calendar

import WeekScreen from '@/components/week/WeekScreen';

export default function CurrentWeekPage() {
  return <WeekScreen iso={null} />;
}
