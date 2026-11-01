// [review:need-review] PHASE-01/206, #311
// summary: tests for useQuickMarks — a tap or an undo that went through tells the screen which category's day moved, a refused one tells it nothing, and a tap taken back from the day's list repaints the card and retires the offer to undo that same tap
// summary: #311 round 2 — a tap behind one that hangs goes out after TAP_TURN_WAIT_MS
// summary: #311 — a tap is on screen before the server answers, five taps with the third refused leave four and retry the third under its own key, the newest answer wins once the burst is over, and a re-visit draws the buttons from the cache

import { afterEach, beforeEach, describe, expect, it, jest, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { QuickMark, QuickMarkEvent, QuickMarkUndo } from '@/lib/api';

const realApi = await import('@/lib/api');

let listMarks: ReturnType<typeof mock>;
let tapMark: ReturnType<typeof mock>;
let undoMark: ReturnType<typeof mock>;

// The real module stays under the entry this suite replaces: the export names
// of a module are fixed by whichever suite links it first, so a mock carrying
// only `quickMarksAPI` would take every other name from the suites after it.
mock.module('@/lib/api', () => ({
  ...realApi,
  quickMarksAPI: {
    ...realApi.quickMarksAPI,
    list: () => listMarks(),
    tap: (id: number, _tap: unknown, key?: string) => tapMark(id, key),
    undo: (eventId: number) => undoMark(eventId),
  },
}));

const { useQuickMarks, TAP_FAILED, TAP_TURN_WAIT_MS, UNDO_FAILED } = await import('./useQuickMarks');

const PUSH_UPS: QuickMark = {
  id: 3,
  label: 'Отжимания',
  category_id: 5,
  field_id: 9,
  kind: 'increment',
  step: 25,
  unit_label: null,
  icon: null,
  color: null,
  hotkey: null,
  order: 0,
  show_in_agent: true,
  is_active: true,
  entry_date: '2026-10-25',
  today_total: 100,
  done: true,
  planned: false,
  plan_item_id: null,
};

const SQUATS: QuickMark = { ...PUSH_UPS, id: 4, label: 'Приседания', category_id: 6 };

function tapAnswer(markId: number, eventId: number, total: number): QuickMarkEvent {
  return {
    event_id: eventId,
    quick_mark_id: markId,
    entry_id: 40,
    entry_date: '2026-10-25',
    occurred_at: '2026-10-25T08:00:00Z',
    today_total: total,
    done: true,
  };
}

function undoAnswer(markId: number, eventId: number, total: number): QuickMarkUndo {
  return {
    event_id: eventId,
    quick_mark_id: markId,
    entry_date: '2026-10-25',
    undone_at: '2026-10-25T08:01:00Z',
    today_total: total,
    done: total > 0,
  };
}

beforeEach(() => {
  listMarks = mock(() => Promise.resolve([PUSH_UPS, SQUATS]));
  tapMark = mock((id: number) => Promise.resolve(tapAnswer(id, 11, 125)));
  undoMark = mock((eventId: number) => Promise.resolve(undoAnswer(3, eventId, 75)));
});

afterEach(() => {
  cleanup();
});

async function renderMarks(onDayChanged?: (categoryId: number) => void) {
  const rendered = renderHook(() => useQuickMarks({ onDayChanged }));
  await waitFor(() => expect(rendered.result.current.loading).toBe(false));
  return rendered;
}

describe('useQuickMarks: telling the screen the day moved', () => {
  it('names the category of the button that was tapped', async () => {
    const onDayChanged = mock<(categoryId: number) => void>(() => {});
    const { result } = await renderMarks(onDayChanged);

    await act(async () => {
      await result.current.tap(SQUATS.id);
    });

    expect(onDayChanged).toHaveBeenCalledTimes(1);
    expect(onDayChanged.mock.calls[0][0]).toBe(SQUATS.category_id);
  });

  it('tells it once per tap, so five taps are five re-reads and no tap is skipped', async () => {
    const onDayChanged = mock<(categoryId: number) => void>(() => {});
    const { result } = await renderMarks(onDayChanged);

    for (let tap = 0; tap < 5; tap += 1) {
      await act(async () => {
        await result.current.tap(PUSH_UPS.id);
      });
    }

    expect(onDayChanged).toHaveBeenCalledTimes(5);
  });

  it('tells nothing when the tap did not reach the server', async () => {
    tapMark = mock(() => Promise.reject(new Error('offline')));
    const onDayChanged = mock<(categoryId: number) => void>(() => {});
    const { result } = await renderMarks(onDayChanged);

    await act(async () => {
      await result.current.tap(PUSH_UPS.id);
    });

    expect(onDayChanged).not.toHaveBeenCalled();
    expect(result.current.error).toBe(TAP_FAILED);
  });

  it('tells it after the quick undo of the last tap as well', async () => {
    const onDayChanged = mock<(categoryId: number) => void>(() => {});
    const { result } = await renderMarks(onDayChanged);
    await act(async () => {
      await result.current.tap(PUSH_UPS.id);
    });
    onDayChanged.mockClear();

    await act(async () => {
      await result.current.undo();
    });

    expect(onDayChanged).toHaveBeenCalledTimes(1);
    expect(onDayChanged.mock.calls[0][0]).toBe(PUSH_UPS.category_id);
  });

  it('works for a screen that asks for nothing', async () => {
    const { result } = await renderMarks();

    await act(async () => {
      await result.current.tap(PUSH_UPS.id);
    });

    expect(result.current.marks[0].today_total).toBe(125);
  });
});

describe('useQuickMarks.undoEvent: a tap taken back from the day list', () => {
  it('sends the event the row named, not the last tap', async () => {
    const { result } = await renderMarks();
    await act(async () => {
      await result.current.tap(PUSH_UPS.id);
    });

    await act(async () => {
      await result.current.undoEvent(99);
    });

    expect(undoMark).toHaveBeenCalledTimes(1);
    expect(undoMark.mock.calls[0][0]).toBe(99);
  });

  it('repaints the card from the answer and tells the screen which day moved', async () => {
    const onDayChanged = mock<(categoryId: number) => void>(() => {});
    const { result } = await renderMarks(onDayChanged);

    let outcome = 'unset' as string | null;
    await act(async () => {
      outcome = await result.current.undoEvent(99);
    });

    expect(outcome).toBeNull();
    expect(result.current.marks[0].today_total).toBe(75);
    expect(onDayChanged).toHaveBeenCalledTimes(1);
    expect(onDayChanged.mock.calls[0][0]).toBe(PUSH_UPS.category_id);
  });

  it('retires the offer to undo the very tap the list just took back', async () => {
    const { result } = await renderMarks();
    await act(async () => {
      await result.current.tap(PUSH_UPS.id);
    });
    expect(result.current.lastEvent?.event_id).toBe(11);

    await act(async () => {
      await result.current.undoEvent(11);
    });

    expect(result.current.lastEvent).toBeNull();
  });

  it('keeps the offer for a tap other than the one that was taken back', async () => {
    const { result } = await renderMarks();
    await act(async () => {
      await result.current.tap(PUSH_UPS.id);
    });

    await act(async () => {
      await result.current.undoEvent(5);
    });

    expect(result.current.lastEvent?.event_id).toBe(11);
  });

  it("answers a refusal with the server's sentence and leaves the day alone", async () => {
    undoMark = mock(() =>
      Promise.reject(new Error('the value was changed outside the journal'))
    );
    const onDayChanged = mock<(categoryId: number) => void>(() => {});
    const { result } = await renderMarks(onDayChanged);

    let outcome = null as string | null;
    await act(async () => {
      outcome = await result.current.undoEvent(99);
    });

    expect(outcome).toBe('the value was changed outside the journal');
    expect(result.current.marks[0].today_total).toBe(100);
    expect(onDayChanged).not.toHaveBeenCalled();
  });

  it('has a sentence of its own when the refusal carries none', async () => {
    undoMark = mock(() => Promise.reject('boom'));
    const { result } = await renderMarks();

    let outcome = null as string | null;
    await act(async () => {
      outcome = await result.current.undoEvent(99);
    });

    expect(outcome).toBe(UNDO_FAILED);
  });
});

/** A promise and the hands that settle it, so a test decides when the server answers. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const totalOf = (marks: QuickMark[], id: number) => marks.find((mark) => mark.id === id)?.today_total;

describe('useQuickMarks: a tap does not wait for the server', () => {
  it('draws the step on the button while the request is still out', async () => {
    tapMark = mock(() => new Promise<QuickMarkEvent>(() => {}));
    const { result } = await renderMarks();

    act(() => {
      void result.current.tap(PUSH_UPS.id);
    });

    expect(totalOf(result.current.marks, PUSH_UPS.id)).toBe(125);
    await waitFor(() => expect(tapMark).toHaveBeenCalledTimes(1));
    expect(tapMark.mock.calls[0][1]).toMatch(/^tap-/);
    expect(totalOf(result.current.marks, PUSH_UPS.id)).toBe(125);
  });

  it('five taps with the third refused leave four, and only the third is taken off', async () => {
    const fourth = deferred<QuickMarkEvent>();
    const keys: (string | undefined)[] = [];
    const firstAttempts: (string | undefined)[] = [];
    tapMark = mock((_id: number, key?: string) => {
      keys.push(key);
      if (!firstAttempts.includes(key)) firstAttempts.push(key);
      const tap = firstAttempts.indexOf(key) + 1;
      // The third tap fails on both attempts; the fourth waits for the test to answer.
      if (tap === 3) return Promise.reject(new Error('offline'));
      if (tap === 4) return fourth.promise;
      return Promise.resolve(tapAnswer(PUSH_UPS.id, 20 + tap, 100 + 25 * (tap < 3 ? tap : tap - 1)));
    });
    const { result } = await renderMarks();

    const taps: Promise<void>[] = [];
    act(() => {
      for (let n = 0; n < 5; n += 1) taps.push(result.current.tap(PUSH_UPS.id));
    });
    expect(totalOf(result.current.marks, PUSH_UPS.id)).toBe(100 + 5 * 25);

    // The third tap has failed both attempts; the fourth is out, the fifth waits behind it.
    await act(async () => {
      await taps[2];
    });
    expect(totalOf(result.current.marks, PUSH_UPS.id)).toBe(100 + 4 * 25);
    expect(result.current.error).toBe(TAP_FAILED);

    await act(async () => {
      fourth.resolve(tapAnswer(PUSH_UPS.id, 24, 175));
      await Promise.all(taps);
    });

    expect(totalOf(result.current.marks, PUSH_UPS.id)).toBe(100 + 4 * 25);
    // The retry of the third tap went out under the key of its first attempt.
    const thirdKey = firstAttempts[2];
    expect(keys.filter((key) => key === thirdKey)).toHaveLength(2);
    expect(new Set(keys).size).toBe(5);
  });

  it("sends one button's taps one after another", async () => {
    const first = deferred<QuickMarkEvent>();
    tapMark = mock(() => (tapMark.mock.calls.length === 1 ? first.promise : Promise.resolve(tapAnswer(PUSH_UPS.id, 31, 150))));
    const { result } = await renderMarks();

    let taps: Promise<void>[] = [];
    act(() => {
      taps = [result.current.tap(PUSH_UPS.id), result.current.tap(PUSH_UPS.id)];
    });
    await act(async () => {});
    expect(tapMark).toHaveBeenCalledTimes(1);
    expect(totalOf(result.current.marks, PUSH_UPS.id)).toBe(150);

    await act(async () => {
      first.resolve(tapAnswer(PUSH_UPS.id, 30, 125));
      await Promise.all(taps);
    });
    expect(tapMark).toHaveBeenCalledTimes(2);
  });

  it('sends the next tap anyway once the one before it has hung for TAP_TURN_WAIT_MS', async () => {
    tapMark = mock(() =>
      tapMark.mock.calls.length === 1 ? new Promise<QuickMarkEvent>(() => {}) : Promise.resolve(tapAnswer(PUSH_UPS.id, 31, 150))
    );
    const { result } = await renderMarks();

    jest.useFakeTimers();
    try {
      await act(async () => {
        void result.current.tap(PUSH_UPS.id);
        void result.current.tap(PUSH_UPS.id);
        await Promise.resolve();
      });
      await act(async () => {
        jest.advanceTimersByTime(TAP_TURN_WAIT_MS - 1);
        await Promise.resolve();
      });
      expect(tapMark).toHaveBeenCalledTimes(1);

      await act(async () => {
        jest.advanceTimersByTime(1);
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(tapMark).toHaveBeenCalledTimes(2);
    } finally {
      jest.useRealTimers();
    }
  });

  it('takes the newest answer once the button has no tap in flight', async () => {
    let answerNo = 0;
    // Another device moved the sum meanwhile: the last answer carries more than two steps.
    tapMark = mock(() => {
      answerNo += 1;
      return Promise.resolve(answerNo === 1 ? tapAnswer(PUSH_UPS.id, 30, 125) : tapAnswer(PUSH_UPS.id, 31, 300));
    });
    const { result } = await renderMarks();

    await act(async () => {
      await Promise.all([result.current.tap(PUSH_UPS.id), result.current.tap(PUSH_UPS.id)]);
    });

    expect(totalOf(result.current.marks, PUSH_UPS.id)).toBe(300);
    expect(result.current.lastEvent?.event_id).toBe(31);
  });

  it('does not ask a refusal again', async () => {
    tapMark = mock(() => Promise.reject(new realApi.APIError(404, 'Quick mark not found')));
    const { result } = await renderMarks();

    await act(async () => {
      await result.current.tap(PUSH_UPS.id);
    });

    expect(tapMark).toHaveBeenCalledTimes(1);
    expect(totalOf(result.current.marks, PUSH_UPS.id)).toBe(100);
    expect(result.current.error).toBe('Quick mark not found');
  });
});

describe('useQuickMarks: a re-visit', () => {
  it('draws the buttons in the first frame while the directory is read again', async () => {
    const first = await renderMarks();
    first.unmount();
    listMarks = mock(() => new Promise<QuickMark[]>(() => {}));

    const { result } = renderHook(() => useQuickMarks());

    expect(result.current.loading).toBe(false);
    expect(result.current.marks.map((mark) => mark.id)).toEqual([PUSH_UPS.id, SQUATS.id]);
  });
});
