'use client';
// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: shared "refetch when the tab/app becomes visible again" wiring, extracted from app/table/page.tsx

import { useEffect } from 'react';

/**
 * `visibilitychange` is the only one of the three that targets `document`;
 * `focus` and `pageshow` are dispatched at `window` and do not bubble down, so
 * they must be registered separately. They are not redundant with
 * `visibilitychange`: an installed PWA that is merely refocused does not always
 * flip `visibilityState`, and a bfcache restore fires `pageshow` alone.
 */
const DOCUMENT_REFRESH_EVENTS = ['visibilitychange'] as const;
const WINDOW_REFRESH_EVENTS = ['focus', 'pageshow'] as const;

/**
 * Returning to a tab fires several of those events in a row (typically
 * `visibilitychange` and then `focus`, in separate tasks). They describe one
 * user action, so refreshes closer together than this are collapsed into the
 * first one — otherwise a screen like /table fires two parallel request sets.
 */
const REFRESH_DEDUPE_MS = 250;

/**
 * Re-run `refresh` every time the tab/app becomes visible again, at most once
 * per return.
 *
 * Installed as a PWA the page is never reloaded, so a screen would otherwise
 * keep rendering the snapshot it fetched on mount — an entry added on /today
 * would not show up on /table or /m/today until a manual reload.
 *
 * Events arriving while the document is hidden are dropped: a backgrounded tab
 * must not fire requests.
 *
 * `refresh` must be stable (wrap it in `useCallback`); an unstable identity
 * re-subscribes on every render.
 */
export function useRefreshOnVisible(refresh: () => void): void {
  useEffect(() => {
    const doc = document;
    const win = window;

    let lastRefreshAt = Number.NEGATIVE_INFINITY;
    const handler = () => {
      if (doc.visibilityState !== 'visible') return;
      const now = Date.now();
      if (now - lastRefreshAt < REFRESH_DEDUPE_MS) return;
      lastRefreshAt = now;
      refresh();
    };

    for (const type of DOCUMENT_REFRESH_EVENTS) doc.addEventListener(type, handler);
    for (const type of WINDOW_REFRESH_EVENTS) win.addEventListener(type, handler);
    return () => {
      for (const type of DOCUMENT_REFRESH_EVENTS) doc.removeEventListener(type, handler);
      for (const type of WINDOW_REFRESH_EVENTS) win.removeEventListener(type, handler);
    };
  }, [refresh]);
}
