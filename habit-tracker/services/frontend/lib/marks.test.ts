// [review:need-review] PHASE-03/88
// summary: tests for the mark ring — three clicks return a line to empty, `skipped` is off the ring and a click takes it off, and the header line never folds `skipped` into done or failed

import { describe, expect, it } from 'bun:test';
import type { Mark } from '@/lib/api';
import {
  MARK_CYCLE,
  marksByItem,
  nextMarkState,
  noteOf,
  stateOf,
  taskCountsLine,
} from '@/lib/marks';

const mark = (itemId: string, overrides: Partial<Mark> = {}): Mark => ({
  item_id: itemId,
  state: 'done',
  note: null,
  marked_at: '2026-08-30T09:00:00Z',
  updated_at: '2026-08-30T09:00:00Z',
  source: 'web',
  ...overrides,
});

describe('nextMarkState', () => {
  it('walks пусто → done → failed → пусто', () => {
    expect(nextMarkState(null)).toBe('done');
    expect(nextMarkState('done')).toBe('failed');
    expect(nextMarkState('failed')).toBeNull();
  });

  it('mirrors the ring the server keeps', () => {
    // The same list lives in `app/day/marks.py`. Written as data on both sides
    // so that the two can be compared by eye rather than by reading two
    // if-chains and hoping.
    expect(MARK_CYCLE).toEqual([null, 'done', 'failed']);
  });

  it('takes a line off `skipped` rather than leaving it stuck', () => {
    // `skipped` is set deliberately, never walked into; a click on a line that
    // was set aside has to do something, and the harmless something is to hand
    // it back to the ring.
    expect(MARK_CYCLE).not.toContain('skipped');
    expect(nextMarkState('skipped')).toBeNull();
  });
});

describe('marksByItem', () => {
  it('reads a state and a note by item id, and empties for a line with none', () => {
    const marks = marksByItem([mark('i1', { note: 'вышло дольше' })]);

    expect(stateOf(marks, 'i1')).toBe('done');
    expect(noteOf(marks, 'i1')).toBe('вышло дольше');
    expect(stateOf(marks, 'i2')).toBeNull();
    expect(noteOf(marks, 'i2')).toBe('');
  });
});

describe('taskCountsLine', () => {
  it('counts a skipped task as neither closed nor failed', () => {
    const line = taskCountsLine({
      planned: 4,
      done: 2,
      failed: 1,
      skipped: 1,
      pending: 0,
    });

    expect(line).toBe('закрыто 2 из 4 · не сделано 1 · снято 1');
  });

  it('says nothing about failures or skips when there are none', () => {
    const line = taskCountsLine({
      planned: 3,
      done: 3,
      failed: 0,
      skipped: 0,
      pending: 0,
    });

    expect(line).toBe('закрыто 3 из 3');
  });
});
