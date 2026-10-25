// [review:need-review] PHASE-01/206
// summary: tests for the list of a day's sets — every tap its own row with time and amount, the day's total from the card, a taken-back set kept and marked, the undo offered only where the server says it will be taken, its refusal shown in the list, the list read again after an undo, and the empty and failed reads

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { QuickMark, QuickMarkDayEvent } from '@/lib/api';
import { clockTime } from '@/lib/today-entries';

const realApi = await import('@/lib/api');

let dayEvents: ReturnType<typeof mock>;

// The real module stays under the one entry this list reads: the export names
// of a module are fixed by whichever suite links it first, so a mock that
// carried only `quickMarksAPI` would take every other name away from the suites
// that run after this one.
mock.module('@/lib/api', () => ({
  ...realApi,
  quickMarksAPI: {
    ...realApi.quickMarksAPI,
    dayEvents: (categoryId: number) => dayEvents(categoryId),
  },
}));

const { default: QuickMarkDaySets } = await import('./QuickMarkDaySets');

const FIRST_AT = '2026-10-25T08:00:00Z';
const SECOND_AT = '2026-10-25T09:30:00Z';
const THIRD_AT = '2026-10-25T11:45:00Z';

function markOf(overrides: Partial<QuickMark> = {}): QuickMark {
  return {
    id: 3,
    label: 'Отжимания',
    category_id: 5,
    field_id: 9,
    kind: 'increment',
    step: 25,
    unit_label: 'раз',
    icon: null,
    color: null,
    hotkey: null,
    order: 0,
    show_in_agent: true,
    is_active: true,
    entry_date: '2026-10-25',
    today_total: 75,
    done: true,
    planned: false,
    plan_item_id: null,
    ...overrides,
  };
}

function setOf(overrides: Partial<QuickMarkDayEvent> = {}): QuickMarkDayEvent {
  return {
    event_id: 1,
    quick_mark_id: 3,
    label: 'Отжимания',
    kind: 'increment',
    unit_label: 'раз',
    entry_date: '2026-10-25',
    occurred_at: FIRST_AT,
    delta: 25,
    bool_value: null,
    undone_at: null,
    undoable: false,
    ...overrides,
  };
}

/** Three sets in the order they were made; only the last one can be taken back. */
function threeSets(): QuickMarkDayEvent[] {
  return [
    setOf({ event_id: 1, occurred_at: FIRST_AT }),
    setOf({ event_id: 2, occurred_at: SECOND_AT, delta: 30 }),
    setOf({ event_id: 3, occurred_at: THIRD_AT, undoable: true }),
  ];
}

async function renderList(
  onUndo = mock<(eventId: number) => Promise<string | null>>(() => Promise.resolve(null)),
  mark = markOf()
) {
  render(<QuickMarkDaySets mark={mark} onUndo={onUndo} />);
  await waitFor(() => expect(screen.queryByText(/Загружаю/)).toBeNull());
  return onUndo;
}

beforeEach(() => {
  dayEvents = mock(() => Promise.resolve(threeSets()));
});

afterEach(() => {
  cleanup();
});

describe('QuickMarkDaySets', () => {
  it('reads the sets of the category the card belongs to', async () => {
    await renderList();

    expect(dayEvents).toHaveBeenCalledTimes(1);
    expect(dayEvents.mock.calls[0][0]).toBe(5);
  });

  it('shows every tap as its own row with its time and its amount', async () => {
    await renderList();

    const rows = within(screen.getByRole('list', { name: 'Подходы за сегодня' })).getAllByRole(
      'listitem'
    );
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText(clockTime(FIRST_AT))).toBeDefined();
    expect(within(rows[0]).getByText('+25 раз')).toBeDefined();
    expect(within(rows[1]).getByText(clockTime(SECOND_AT))).toBeDefined();
    expect(within(rows[1]).getByText('+30 раз')).toBeDefined();
    expect(within(rows[2]).getByText(clockTime(THIRD_AT))).toBeDefined();
  });

  it("prints the day's total as the card does", async () => {
    await renderList();

    expect(screen.getByText('Итого за день: 75 раз')).toBeDefined();
  });

  it('prints no total for a button that has none', async () => {
    dayEvents = mock(() =>
      Promise.resolve([setOf({ delta: null, bool_value: true, undoable: true })])
    );
    await renderList(undefined, markOf({ kind: 'check', today_total: null, unit_label: null }));

    expect(screen.queryByText(/Итого/)).toBeNull();
    expect(screen.getByText('Отмечено')).toBeDefined();
    expect(screen.getByRole('list', { name: 'Отметки за сегодня' })).toBeDefined();
  });

  it('keeps a taken-back set in the list, marked, with no undo of its own', async () => {
    dayEvents = mock(() =>
      Promise.resolve([
        setOf({ event_id: 1 }),
        setOf({ event_id: 2, undone_at: '2026-10-25T08:05:00Z', occurred_at: SECOND_AT }),
      ])
    );
    await renderList();

    const rows = screen.getAllByRole('listitem');
    expect(within(rows[1]).getByText('отменён')).toBeDefined();
    expect(within(rows[0]).queryByText('отменён')).toBeNull();
    expect(screen.queryByRole('button', { name: /Отменить/ })).toBeNull();
  });

  it('offers the undo only on the tap the server says it will take', async () => {
    await renderList();

    const buttons = screen.getAllByRole('button', { name: /Отменить/ });
    expect(buttons).toHaveLength(1);
    expect(buttons[0].getAttribute('aria-label')).toBe(
      `Отменить: +25 раз в ${clockTime(THIRD_AT)}`
    );
  });

  it('names the button of each set only when the category has more than one', async () => {
    await renderList();
    expect(screen.queryByText('Отжимания')).toBeNull();
    cleanup();

    dayEvents = mock(() =>
      Promise.resolve([
        setOf({ event_id: 1, quick_mark_id: 3, label: 'Отжимания' }),
        setOf({ event_id: 2, quick_mark_id: 4, label: 'Отжимания узко', occurred_at: SECOND_AT }),
      ])
    );
    await renderList();

    expect(screen.getByText('Отжимания узко')).toBeDefined();
  });

  it('hands the tap to the screen and reads the list again once it is taken back', async () => {
    const onUndo = mock<(eventId: number) => Promise<string | null>>(() => Promise.resolve(null));
    await renderList(onUndo);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Отменить/ }));
    });

    expect(onUndo).toHaveBeenCalledTimes(1);
    expect(onUndo.mock.calls[0][0]).toBe(3);
    await waitFor(() => expect(dayEvents).toHaveBeenCalledTimes(2));
  });

  it('shows the sentence of a refusal and still reads the list again', async () => {
    const onUndo = mock<(eventId: number) => Promise<string | null>>(() =>
      Promise.resolve('quick mark event 3 is not the last open event')
    );
    await renderList(onUndo);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Отменить/ }));
    });

    expect((await screen.findByRole('alert')).textContent).toContain(
      'quick mark event 3 is not the last open event'
    );
    expect(dayEvents).toHaveBeenCalledTimes(2);
  });

  it('keeps the button from firing a second undo while the first is in flight', async () => {
    let release!: (value: string | null) => void;
    const onUndo = mock<(eventId: number) => Promise<string | null>>(
      () =>
        new Promise<string | null>((resolve) => {
          release = resolve;
        })
    );
    await renderList(onUndo);

    fireEvent.click(screen.getByRole('button', { name: /Отменить/ }));
    fireEvent.click(screen.getByRole('button', { name: /Отменить/ }));

    expect(onUndo).toHaveBeenCalledTimes(1);
    await act(async () => release(null));
  });

  it('says so when nothing was marked today', async () => {
    dayEvents = mock(() => Promise.resolve([] as QuickMarkDayEvent[]));
    await renderList();

    expect(screen.getByText('За сегодня пока ничего не отмечено.')).toBeDefined();
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('says the read failed and reads again on request', async () => {
    dayEvents = mock(() => Promise.reject(new Error('network down')));
    await renderList();

    expect((await screen.findByRole('alert')).textContent).toContain('network down');

    dayEvents = mock(() => Promise.resolve(threeSets()));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    });

    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(3));
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
