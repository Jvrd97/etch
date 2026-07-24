// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: unit tests for useRefreshOnVisible — one refresh per return to the tab, unmount cleanup, re-subscription

import { afterEach, describe, expect, it } from 'bun:test';
import { act, cleanup, renderHook } from '@testing-library/react';
import { useRefreshOnVisible } from './useRefreshOnVisible';

/** Comfortably longer than the hook's internal dedupe window. */
const AFTER_DEDUPE_MS = 400;

afterEach(() => {
  cleanup();
  setVisibility('visible');
});

function setVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
}

/** Replays the event burst a real browser fires when a tab is re-entered. */
function fireReturnToTab(): void {
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event('focus'));
    window.dispatchEvent(new Event('pageshow'));
  });
}

async function waitOutDedupeWindow(): Promise<void> {
  await act(async () => {
    await Bun.sleep(AFTER_DEDUPE_MS);
  });
}

describe('useRefreshOnVisible', () => {
  it('refreshes once per return to the tab, not once per event', () => {
    let calls = 0;
    renderHook(() => useRefreshOnVisible(() => void (calls += 1)));

    fireReturnToTab();

    expect(calls).toBe(1);
  });

  it('refreshes again on the next return, once the dedupe window has passed', async () => {
    let calls = 0;
    renderHook(() => useRefreshOnVisible(() => void (calls += 1)));

    fireReturnToTab();
    await waitOutDedupeWindow();
    fireReturnToTab();

    expect(calls).toBe(2);
  });

  it('ignores events fired while the document is hidden', () => {
    let calls = 0;
    renderHook(() => useRefreshOnVisible(() => void (calls += 1)));

    setVisibility('hidden');
    fireReturnToTab();

    expect(calls).toBe(0);
  });

  it('removes its listeners on unmount', () => {
    let calls = 0;
    const { unmount } = renderHook(() => useRefreshOnVisible(() => void (calls += 1)));

    unmount();
    fireReturnToTab();

    expect(calls).toBe(0);
  });

  it('re-subscribes when the refresh identity changes', async () => {
    let first = 0;
    let second = 0;
    const { rerender } = renderHook(
      ({ refresh }: { refresh: () => void }) => useRefreshOnVisible(refresh),
      { initialProps: { refresh: () => void (first += 1) } }
    );

    rerender({ refresh: () => void (second += 1) });
    await waitOutDedupeWindow();
    fireReturnToTab();

    expect(first).toBe(0);
    expect(second).toBe(1);
  });
});
