// [review:need-review] PHASE-01/206
// summary: tests for useQuickMarks — a tap or an undo that went through tells the screen which category's day moved, a refused one tells it nothing, and a tap taken back from the day's list repaints the card and retires the offer to undo that same tap

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
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
    tap: (id: number) => tapMark(id),
    undo: (eventId: number) => undoMark(eventId),
  },
}));

const { useQuickMarks, UNDO_FAILED } = await import('./useQuickMarks');

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
    expect(result.current.error).toBe('offline');
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
