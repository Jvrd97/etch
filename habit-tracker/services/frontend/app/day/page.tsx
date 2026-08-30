'use client';
// [review:need-review] PHASE-03/86
// summary: /day — the entry point from the navigation; the day is left unnamed so the server answers with today by its own boundary, not by the browser calendar

import DayScreen from '@/components/DayScreen';

export default function TodayDayPage() {
  return <DayScreen date={null} />;
}
