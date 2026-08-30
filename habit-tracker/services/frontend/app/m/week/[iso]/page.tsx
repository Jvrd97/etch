'use client';
// [review:need-review] PHASE-03/94
// summary: /m/week/[iso] — mobile twin of the week page, same screen on the mobile type scale

import { useParams } from 'next/navigation';
import WeekScreen from '@/components/week/WeekScreen';

export default function MobileWeekPage() {
  const params = useParams<{ iso: string }>();
  return <WeekScreen iso={params.iso} compact />;
}
