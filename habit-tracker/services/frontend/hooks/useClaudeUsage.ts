'use client';
// [review:need-review] PHASE-03/220
// summary: reads the Claude Code totals of the day on screen for the block on the day screen — once per day, then every minute while that day is the server's today (the one still growing); an answer for another day is never returned, and a failed read leaves the block out rather than breaking the day

import { useEffect, useState } from 'react';
// A namespace import read at call time, as in `useAgentStatus`: suites that mock
// `@/lib/api` with a fixed list of names must still link every screen of the day.
import * as api from '@/lib/api';
import type { ClaudeUsageDay } from '@/lib/api';

/** The agent restates a session every five minutes; a minute keeps the block close enough. */
export const CLAUDE_USAGE_REFRESH_MS = 60_000;

/** The read and the pace, as parameters so tests need no module mock. Keep the object stable between renders. */
export interface ClaudeUsageSource {
  read: (date: string) => Promise<ClaudeUsageDay>;
  refreshMs: number;
}

const API_SOURCE: ClaudeUsageSource = {
  read: (date) => api.agentAPI.claudeUsage(date),
  refreshMs: CLAUDE_USAGE_REFRESH_MS,
};

/** The totals of `date`, or null before the first answer, without a date, and after a failed first read. */
export function useClaudeUsage(
  date: string | null,
  source: ClaudeUsageSource = API_SOURCE
): ClaudeUsageDay | null {
  const [usage, setUsage] = useState<ClaudeUsageDay | null>(null);

  useEffect(() => {
    if (date === null) return;
    let alive = true;
    let timer: ReturnType<typeof setInterval> | null = null;
    const load = () => {
      source
        .read(date)
        .then((body) => {
          if (!alive) return;
          setUsage(body);
          // Only the server's today still grows; the totals of a past day are final.
          if (body.date !== body.today && timer !== null) {
            clearInterval(timer);
            timer = null;
          }
        })
        .catch(() => {
          // Keep what was shown: one lost read is not news about the day.
        });
    };
    load();
    timer = setInterval(load, source.refreshMs);
    return () => {
      alive = false;
      if (timer !== null) clearInterval(timer);
    };
  }, [date, source]);

  return usage !== null && usage.date === date ? usage : null;
}
