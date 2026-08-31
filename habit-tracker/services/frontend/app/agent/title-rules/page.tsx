'use client';
// [review:need-review] PHASE-03/158
// summary: /agent/title-rules — the desktop entry point of the window-title privacy screen; the screen itself lives in components/agent, so this page only names it

import TitleRuleList from '@/components/agent/TitleRuleList';

export default function TitleRulesPage() {
  return <TitleRuleList />;
}
