'use client';
// [review:need-review] PHASE-03/221
// summary: /week/review/[iso] — the review of one named week; the code goes to the API untouched so a bad one comes back as the server's 404

import { useParams } from 'next/navigation';
import WeekReviewScreen from '@/components/week-review/WeekReviewScreen';

export default function WeekReviewPage() {
  const params = useParams<{ iso: string }>();
  return <WeekReviewScreen iso={params.iso} />;
}
