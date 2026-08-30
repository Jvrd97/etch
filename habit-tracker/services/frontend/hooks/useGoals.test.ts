// [review:need-review] PHASE-03/93
// summary: tests for useGoals — a failed read clears the stale board instead of leaving it on screen, closing a milestone re-reads the whole board because a dependency chip elsewhere changes with it, a refused PATCH surfaces as an error and still leaves `saving`, and a request that lands after unmount touches nothing

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { GoalsPayload, Milestone } from '@/lib/api';

function milestone(code: string, status: Milestone['status'] = 'open'): Milestone {
  return {
    code,
    title: `Милстон ${code}`,
    done_criterion: 'сделано',
    when_text: 'сейчас',
    ord: Number(code.slice(1)),
    status,
    done_on: null,
    depends_on: [],
  };
}

const BOARD: GoalsPayload = {
  levels: [
    { level: 0, title: 'точка', body_md: '', open_questions: [] },
  ],
  milestones: [milestone('M9'), milestone('M10')],
  quarter: '2026-Q3',
  goals: [
    {
      id: 1,
      quarter: '2026-Q3',
      ord: 1,
      text_md: 'Денежный контур',
      milestone_code: null,
      status: 'open',
    },
  ],
};

let getBoard: ReturnType<typeof mock>;
let patchMilestone: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export *names*
// the first time anything links against it and shares that registry across the
// run, so a partial mock here would delete members other suites reach for.
mock.module('@/lib/api', () => ({
  dailySummaryAPI: {
    draft: () => Promise.resolve({ metrics: [], unresolved: [] }),
    apply: () => Promise.resolve({ entry_ids: [] }),
  },
  onboardingAPI: { draft: () => Promise.resolve({ operations: [] }) },
  insightsAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  categoriesAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  journalAPI: {
    getAll: () => Promise.resolve({ items: [], total: 0 }),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  dayAPI: {
    getToday: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
    openToday: () => Promise.resolve(null),
    open: () => Promise.resolve(null),
    savePlan: () => Promise.resolve(null),
    setMark: () => Promise.resolve(null),
    saveNotebook: () => Promise.resolve(null),
    close: () => Promise.resolve(null),
  },
  goalsAPI: {
    get: () => getBoard(),
    patchMilestone: (code: string, status: string) =>
      patchMilestone(code, status),
  },
}));

const { useGoals } = await import('./useGoals');

beforeEach(() => {
  getBoard = mock(() => Promise.resolve(BOARD));
  patchMilestone = mock(() => Promise.resolve(milestone('M9', 'done')));
});

afterEach(() => {
  cleanup();
});

describe('useGoals', () => {
  it('reads the whole board in one request', async () => {
    const { result } = renderHook(() => useGoals());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(getBoard).toHaveBeenCalledTimes(1);
    expect(result.current.payload).toEqual(BOARD);
    expect(result.current.error).toBeNull();
  });

  it('does not keep showing a board that failed to load', async () => {
    getBoard = mock(() => Promise.reject(new Error('502: цели не читаются')));

    const { result } = renderHook(() => useGoals());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.payload).toBeNull();
    expect(result.current.error).toContain('цели не читаются');
  });

  it('re-reads the board after a milestone moves', async () => {
    // Closing M9 is not a fact about M9 alone: M10 waits on it, and its
    // dependency chip has to change appearance in the same paint. Patching one
    // row into the state already in hand would leave the graph telling the old
    // story.
    const { result } = renderHook(() => useGoals());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.markMilestone('M9', 'done'));

    await waitFor(() => expect(getBoard).toHaveBeenCalledTimes(2));
    expect(patchMilestone).toHaveBeenCalledWith('M9', 'done');
    await waitFor(() => expect(result.current.saving.has('M9')).toBe(false));
  });

  it('shows a refused move instead of swallowing it, and stops saying "saving"', async () => {
    patchMilestone = mock(() =>
      Promise.reject(new Error('404: Милстона M42 нет.'))
    );
    const { result } = renderHook(() => useGoals());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.markMilestone('M42', 'done'));

    await waitFor(() => expect(result.current.error).toContain('M42'));
    expect(result.current.saving.has('M42')).toBe(false);
    // The board was never re-read: nothing changed on the server.
    expect(getBoard).toHaveBeenCalledTimes(1);
  });

  it('lets a request that lands after unmount go nowhere', async () => {
    // Without the `cancelled` flag the resolved read would call `setPayload` on
    // a hook nobody is rendering, which React reports as a warning and which
    // hides a real bug: a board arriving for a screen that has been left.
    let settle: (payload: GoalsPayload) => void = () => undefined;
    getBoard = mock(
      () =>
        new Promise<GoalsPayload>((resolve) => {
          settle = resolve;
        })
    );

    const { result, unmount } = renderHook(() => useGoals());
    unmount();
    await act(async () => {
      settle(BOARD);
    });

    expect(result.current.payload).toBeNull();
    expect(result.current.loading).toBe(true);
  });
});
