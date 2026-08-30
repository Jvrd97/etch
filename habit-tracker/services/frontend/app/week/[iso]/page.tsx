'use client';
// [review:need-review] PHASE-03/94
// summary: /week/[iso] — one named week; the code is passed to the API untouched so a bad one comes back as the server's 404 rather than a silently corrected week

import { useParams } from 'next/navigation';
import WeekScreen from '@/components/week/WeekScreen';

export default function WeekPage() {
  const params = useParams<{ iso: string }>();
  return <WeekScreen iso={params.iso} />;
}
