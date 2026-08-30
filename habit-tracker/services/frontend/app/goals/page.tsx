'use client';
// [review:need-review] PHASE-03/93
// summary: /goals — the desktop entry point; the board itself is shared with the mobile twin, so this page only names the screen

import GoalsBoard from '@/components/goals/GoalsBoard';

export default function GoalsPage() {
  return <GoalsBoard />;
}
