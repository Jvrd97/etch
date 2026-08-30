'use client';
// [review:need-review] PHASE-03/94
// summary: /life — the timeline with the day navigation beside it; the grid itself is shared with the mobile twin, so this page only lays the two out

import DaySidebar from '@/components/day/DaySidebar';
import LifeGrid from '@/components/life/LifeGrid';

export default function LifePage() {
  return (
    <div className="lg:grid lg:grid-cols-[16rem_1fr] lg:gap-8">
      <aside className="hidden lg:block">
        <DaySidebar />
      </aside>
      <LifeGrid />
    </div>
  );
}
