// [review:need-review] PHASE-03/121, PHASE-03/124
// summary: tests for the pure reading of the directory — nothing where the day said nothing, the tap's own answer folded back in without a refetch, the categories the directory has taken over, the same fold for an undo, the caption the undo affordance carries, and the key that makes a retried tap the same tap

import { describe, expect, it } from 'bun:test';
import type { QuickMark, QuickMarkEvent } from '@/lib/api';
import {
  applyQuickMarkEvent,
  applyQuickMarkUndo,
  categoriesWithQuickMark,
  formatMarkTotal,
  markCaption,
  newTapKey,
  undoCaption,
} from './quick-marks';

function mark(overrides: Partial<QuickMark> = {}): QuickMark {
  return {
    id: 1,
    label: '+250 мл',
    category_id: 10,
    field_id: 100,
    kind: 'increment',
    step: 250,
    unit_label: 'мл',
    icon: null,
    color: null,
    hotkey: null,
    order: 0,
    show_in_agent: true,
    is_active: true,
    entry_date: '2026-08-30',
    today_total: null,
    done: false,
    planned: false,
    plan_item_id: null,
    ...overrides,
  };
}

describe('formatMarkTotal', () => {
  it('says nothing where the day said nothing', () => {
    expect(formatMarkTotal(null)).toBe('');
  });

  it('keeps a whole number whole', () => {
    expect(formatMarkTotal(1250)).toBe('1250');
  });

  it('drops the trailing zeros of a fraction', () => {
    expect(formatMarkTotal(0.5)).toBe('0.5');
    expect(formatMarkTotal(1.2000000001)).toBe('1.2');
  });

  it('shows a real zero, because "я выпил ноль" is a fact', () => {
    expect(formatMarkTotal(0)).toBe('0');
  });
});

describe('markCaption', () => {
  it('puts the unit next to the total', () => {
    expect(markCaption(mark({ today_total: 1250 }))).toBe('1250 мл');
  });

  it('says nothing at all for a tick', () => {
    expect(markCaption(mark({ kind: 'check', today_total: null }))).toBe('');
  });

  it('omits a unit the button does not carry', () => {
    expect(markCaption(mark({ today_total: 3, unit_label: null }))).toBe('3');
  });
});

describe('applyQuickMarkEvent', () => {
  const event: QuickMarkEvent = {
    event_id: 7,
    quick_mark_id: 1,
    entry_id: 42,
    entry_date: '2026-08-30',
    occurred_at: '2026-08-30T10:00:00Z',
    today_total: 500,
    done: true,
  };

  it('repaints the tapped button from the answer, without a second request', () => {
    const [updated] = applyQuickMarkEvent([mark()], event);
    expect(updated.today_total).toBe(500);
    expect(updated.done).toBe(true);
  });

  it('leaves every other button exactly as it was', () => {
    const other = mark({ id: 2, today_total: 3 });
    const [, untouched] = applyQuickMarkEvent([mark(), other], event);
    expect(untouched).toEqual(other);
  });

  it('ignores an event for a button that is no longer listed', () => {
    const marks = [mark({ id: 9 })];
    expect(applyQuickMarkEvent(marks, event)).toEqual(marks);
  });
});

describe('categoriesWithQuickMark', () => {
  it('is empty for an empty directory, so nothing is hidden', () => {
    expect(categoriesWithQuickMark([]).size).toBe(0);
  });

  it('collects every category the directory answers for', () => {
    const covered = categoriesWithQuickMark([
      mark({ id: 1, category_id: 10 }),
      mark({ id: 2, category_id: 10 }),
      mark({ id: 3, category_id: 11 }),
    ]);
    expect([...covered].sort()).toEqual([10, 11]);
  });
});

describe('applyQuickMarkUndo', () => {
  it('puts back the state the undo answered with, without a refetch', () => {
    const marks = [
      mark({ id: 1, today_total: 750, done: true }),
      mark({ id: 2, today_total: 3, done: true }),
    ];

    const next = applyQuickMarkUndo(marks, {
      event_id: 9,
      quick_mark_id: 1,
      entry_date: '2026-08-30',
      undone_at: '2026-08-30T10:00:00Z',
      today_total: 500,
      done: true,
    });

    expect(next[0].today_total).toBe(500);
    expect(next[1].today_total).toBe(3);
  });

  it('leaves the list alone when the button has since left the directory', () => {
    const marks = [mark({ id: 1, today_total: 250, done: true })];

    const next = applyQuickMarkUndo(marks, {
      event_id: 9,
      quick_mark_id: 99,
      entry_date: '2026-08-30',
      undone_at: '2026-08-30T10:00:00Z',
      today_total: 0,
      done: false,
    });

    expect(next).toEqual(marks);
  });
});

describe('undoCaption', () => {
  const tapped = {
    event_id: 5,
    quick_mark_id: 1,
    entry_id: 42,
    entry_date: '2026-08-30',
    occurred_at: '2026-08-30T10:00:00Z',
    today_total: 250,
    done: true,
  };

  it('names the button, because the offer sits under a row of them', () => {
    expect(undoCaption([mark({ id: 1, label: '+250 мл' })], tapped)).toBe(
      'Отменить «+250 мл»'
    );
  });

  it('has nothing to say when no tap is outstanding', () => {
    expect(undoCaption([mark({ id: 1 })], null)).toBeNull();
  });

  it('has nothing to say about a button that is gone', () => {
    expect(undoCaption([mark({ id: 2 })], tapped)).toBeNull();
  });
});

describe('newTapKey', () => {
  it('gives every tap its own key, so two taps are two taps', () => {
    const keys = new Set(Array.from({ length: 50 }, () => newTapKey()));

    expect(keys.size).toBe(50);
  });
});
