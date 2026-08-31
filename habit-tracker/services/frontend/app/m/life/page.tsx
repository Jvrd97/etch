'use client';
// [review:need-review] PHASE-03/94
// summary: /m/life — mobile entry point; the same timeline as the desktop twin on the mobile type scale, without the sidebar the narrow shell has no room for

import LifeGrid from '@/components/life/LifeGrid';

export default function MobileLifePage() {
  return <LifeGrid compact />;
}
