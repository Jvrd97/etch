'use client';
// [review:need-review] PHASE-03/162
// summary: /agent/mode-schedule — the desktop entry point of the week schedule of the day mode; the screen itself lives in components/agent, so this page only names it

import ModeScheduleEditor from '@/components/agent/ModeScheduleEditor';

export default function ModeSchedulePage() {
  return <ModeScheduleEditor />;
}
