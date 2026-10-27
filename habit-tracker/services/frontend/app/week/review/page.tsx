'use client';
// [review:need-review] PHASE-03/221
// summary: /week/review — the review of the running week; the week is left unnamed so the server picks it by its own day boundary

import WeekReviewScreen from '@/components/week-review/WeekReviewScreen';

export default function CurrentWeekReviewPage() {
  return <WeekReviewScreen iso={null} />;
}
