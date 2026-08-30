'use client';
// [review:need-review] PHASE-03/86
// summary: /day/[date] — one named day; the date is passed through to the API untouched so a bad one comes back as the server's 422 rather than a silently corrected date

import { useParams } from 'next/navigation';
import DayScreen from '@/components/DayScreen';

export default function DayPage() {
  const params = useParams<{ date: string }>();
  return <DayScreen date={params.date} />;
}
