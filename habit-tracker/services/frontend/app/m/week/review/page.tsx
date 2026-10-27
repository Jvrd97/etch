'use client';
// [review:need-review] PHASE-03/221
// summary: /m/week/review — mobile twin of the running week's review, on the mobile type scale

import WeekReviewScreen from '@/components/week-review/WeekReviewScreen';

export default function MobileCurrentWeekReviewPage() {
  return <WeekReviewScreen iso={null} compact />;
}
