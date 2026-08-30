'use client';
// [review:need-review] PHASE-03/93
// summary: /m/goals — mobile entry point; same board as the desktop twin, drawn on the mobile type scale

import GoalsBoard from '@/components/goals/GoalsBoard';

export default function MobileGoalsPage() {
  return <GoalsBoard compact />;
}
