'use client';
// [review:need-review] PHASE-03/164
// summary: reads the agent status for the day screen — once on mount, then every minute — and keeps the last good answer; a failed read leaves the banner out, because a banner about the agent must never break the day

import { useEffect, useState } from 'react';
// A namespace import read at call time, not a named import: suites that mock
// `@/lib/api` with a fixed list of names would fail to link every screen that
// renders the day if this hook imported `agentAPI` by name.
import * as api from '@/lib/api';
import type { AgentStatus } from '@/lib/api';

/** The agent reports every minute; a banner older than that is stale. */
export const AGENT_STATUS_REFRESH_MS = 60_000;

/** The read and the pace, as parameters so tests need no module mock. Keep the object stable between renders. */
export interface AgentStatusSource {
  read: () => Promise<AgentStatus>;
  refreshMs: number;
}

const API_SOURCE: AgentStatusSource = {
  read: () => api.agentAPI.status(),
  refreshMs: AGENT_STATUS_REFRESH_MS,
};

/** The latest status, or null before the first answer and while there never was one. */
export function useAgentStatus(source: AgentStatusSource = API_SOURCE): AgentStatus | null {
  const [status, setStatus] = useState<AgentStatus | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => {
      source
        .read()
        .then((body) => {
          if (alive) setStatus(body);
        })
        .catch(() => {
          // Keep what was shown: one lost read is not news about the agent.
        });
    };
    load();
    const timer = setInterval(load, source.refreshMs);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [source]);

  return status;
}
