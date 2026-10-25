// [review:need-review] PHASE-01/206
// summary: tests for the wording of a day's sets — what one set says it was worth, the heading and the card entry for a number against a tick

import { describe, expect, it } from 'bun:test';
import type { QuickMark, QuickMarkDayEvent } from '@/lib/api';
import {
  TICKED,
  UNTICKED,
  daySetsHeading,
  daySetsOpenLabel,
  setAmount,
} from '@/lib/quick-mark-sets';

function setOf(overrides: Partial<QuickMarkDayEvent> = {}): QuickMarkDayEvent {
  return {
    event_id: 1,
    quick_mark_id: 3,
    label: 'Отжимания',
    kind: 'increment',
    unit_label: null,
    entry_date: '2026-10-25',
    occurred_at: '2026-10-25T08:00:00Z',
    delta: 25,
    bool_value: null,
    undone_at: null,
    undoable: false,
    ...overrides,
  };
}

function markOf(overrides: Partial<QuickMark> = {}): QuickMark {
  return {
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
    today_total: null,
    done: false,
    planned: false,
    plan_item_id: null,
    ...overrides,
  };
}

describe('setAmount', () => {
  it('writes an increment with a plus sign', () => {
    expect(setAmount(setOf({ delta: 25 }))).toBe('+25');
  });

  it('adds the unit the button counts in', () => {
    expect(setAmount(setOf({ delta: 250, unit_label: 'мл' }))).toBe('+250 мл');
  });

  it('drops float noise instead of printing it', () => {
    expect(setAmount(setOf({ delta: 0.1 + 0.2 }))).toBe('+0.3');
  });

  it('keeps the minus of a figure that went down', () => {
    expect(setAmount(setOf({ delta: -400, unit_label: 'мл' }))).toBe('-400 мл');
  });

  it('says what a tick set the box to, in words', () => {
    expect(setAmount(setOf({ delta: null, bool_value: true }))).toBe(TICKED);
    expect(setAmount(setOf({ delta: null, bool_value: false }))).toBe(UNTICKED);
  });

  it('says nothing for a row that carries neither figure', () => {
    expect(setAmount(setOf({ delta: null, bool_value: null }))).toBe('');
  });
});

describe('the wording of the list', () => {
  it('calls the taps of a number sets and the taps of a tick marks', () => {
    expect(daySetsHeading(markOf())).toBe('Подходы за сегодня');
    expect(daySetsHeading(markOf({ kind: 'check' }))).toBe('Отметки за сегодня');
  });

  it('names the button the card entry belongs to', () => {
    expect(daySetsOpenLabel(markOf({ label: 'Приседания' }))).toBe(
      'Подходы за сегодня — Приседания'
    );
  });
});
