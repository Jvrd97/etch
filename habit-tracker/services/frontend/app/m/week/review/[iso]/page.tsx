'use client';
// [review:need-review] PHASE-03/221
// summary: /m/week/review/[iso] — mobile twin of one named week's review, on the mobile type scale

import { useParams } from 'next/navigation';
import WeekReviewScreen from '@/components/week-review/WeekReviewScreen';

export default function MobileWeekReviewPage() {
  const params = useParams<{ iso: string }>();
  return <WeekReviewScreen iso={params.iso} compact />;
}
