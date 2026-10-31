---
name: frontend-test-date-pollution
description: In the frontend bun test run, leaked mock.module('@/lib/date') pins todayISO to 2026-07-24; date-window tests must anchor on todayISO(NOW), not on a literal date
metadata:
  type: project
---

`app/entries/page.test.tsx`, `app/m/entries/page.test.tsx`, `hooks/useToday.test.ts` and `hooks/useEntryDraft.test.ts` call `mock.module('@/lib/date', () => ({ todayISO: () => '2026-07-24' }))`. In the full `bun test` run this pins `todayISO(anything)` to 2026-07-24 for files that run later. Alone or in a pair the same test passes, so the failure shows up only in the full run (a test that builds a date window from a fixed `now` suddenly gets an empty window).

**Why:** found while writing the #78 Trends tests: parity tests between the dashboard row and the category chart returned an empty trend list only in the full run.

**How to apply:** in a test that feeds `now` into code calling `todayISO(now)`, take the anchor from the same function (`const TODAY = todayISO(NOW)`) and derive every date from `TODAY` by plain arithmetic; do not hard-code `'2026-09-30'` style window dates. Baseline full run also has one known failure, `app/m/health/page.test.tsx` (`healthAPI` missing from a shared `@/lib/api` mock); it is not caused by new work.
