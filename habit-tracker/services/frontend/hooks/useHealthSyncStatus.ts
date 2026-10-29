'use client';
// [review:need-review] PHASE-03/132
// summary: reads the pump's sync journal for the Health screens — once on mount, then every minute — and keeps the last good answer; a failed read leaves the block out, because a note about the sync must never break the metrics below it

import { useEffect, useState } from 'react';
// A namespace import read at call time, not a named import: suites that mock
// `@/lib/api` with a fixed list of names would fail to link every screen that
// renders Health if this hook imported `healthAPI` by name.
import * as api from '@/lib/api';
import type { HealthSyncStatus } from '@/lib/api';

/** The journal moves on every chunk; a minute keeps the lag honest without polling hard. */
export const HEALTH_SYNC_STATUS_REFRESH_MS = 60_000;

/** The read and the pace, as parameters so tests need no module mock. Keep the object stable between renders. */
export interface HealthSyncStatusSource {
  read: () => Promise<HealthSyncStatus>;
  refreshMs: number;
}

const API_SOURCE: HealthSyncStatusSource = {
  read: () => api.healthAPI.getSyncStatus(),
  refreshMs: HEALTH_SYNC_STATUS_REFRESH_MS,
};

/** The latest sync status, or null before the first answer and after only failed reads. */
export function useHealthSyncStatus(
  source: HealthSyncStatusSource = API_SOURCE
): HealthSyncStatus | null {
  const [status, setStatus] = useState<HealthSyncStatus | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => {
      // `Promise.resolve().then` also turns a synchronous throw from `read` into a rejection.
      Promise.resolve()
        .then(() => source.read())
        .then((body) => {
          if (alive) setStatus(body);
        })
        .catch(() => {
          // Keep what was shown: one lost read is not news about the pump.
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
