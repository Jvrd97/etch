'use client';
// [review:need-review] PHASE-03/86
// summary: /m/day/[date] — mobile twin of the named-day screen

import { useParams } from 'next/navigation';
import MobileDayScreen from '@/components/mobile/MobileDayScreen';

export default function MobileDayPage() {
  const params = useParams<{ date: string }>();
  return <MobileDayScreen date={params.date} />;
}
