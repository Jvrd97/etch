'use client';
// [review:need-review] PHASE-03/86
// summary: /m/day — mobile entry point; same "let the server name today" rule as the desktop twin

import MobileDayScreen from '@/components/mobile/MobileDayScreen';

export default function MobileTodayDayPage() {
  return <MobileDayScreen date={null} />;
}
