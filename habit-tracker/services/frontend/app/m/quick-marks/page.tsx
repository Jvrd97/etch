'use client';
// [review:need-review] PHASE-03/125
// summary: /m/quick-marks — mobile entry point; same screen as the desktop twin, drawn on the mobile type scale with touch-sized controls

import QuickMarksScreen from '@/components/QuickMarksScreen';

export default function MobileQuickMarksPage() {
  return <QuickMarksScreen compact />;
}
