// [review:need-review] PHASE-01/206
// summary: tests for the day list a Today card opens — a record card opens the category's records, a quick-mark card opens its sets beside them, and a card whose category is not among the active ones still opens its sets

import { describe, expect, it } from 'bun:test';
import { act, renderHook } from '@testing-library/react';
import type { Category, QuickMark } from '@/lib/api';
import { useTodayList } from './useTodayList';

const TIMESTAMP = '2026-10-25T00:00:00Z';

function category(id: number, name: string): Category {
  return {
    id,
    name,
    display_mode: 'form',
    streak_mode: 'build',
    is_active: true,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    fields: [],
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
    today_total: 50,
    done: true,
    planned: false,
    plan_item_id: null,
    ...overrides,
  };
}

const PUSH_UPS = category(5, 'Отжимания');
const SQUATS = category(6, 'Приседания');

describe('useTodayList', () => {
  it('is closed until a card asks for it', () => {
    const { result } = renderHook(() => useTodayList([PUSH_UPS], [markOf()]));

    expect(result.current.open).toBe(false);
    expect(result.current.category).toBeNull();
    expect(result.current.mark).toBeNull();
  });

  it('opens the records of a category without any sets', () => {
    const { result } = renderHook(() => useTodayList([PUSH_UPS, SQUATS], [markOf()]));

    act(() => result.current.openCategory(SQUATS));

    expect(result.current.open).toBe(true);
    expect(result.current.category).toEqual(SQUATS);
    expect(result.current.mark).toBeNull();
    expect(result.current.title).toBe('Приседания — сегодня');
  });

  it('opens the sets of a card together with the records of its category', () => {
    const mark = markOf();
    const { result } = renderHook(() => useTodayList([PUSH_UPS, SQUATS], [mark]));

    act(() => result.current.openMark(mark));

    expect(result.current.category).toEqual(PUSH_UPS);
    expect(result.current.mark).toEqual(mark);
    expect(result.current.title).toBe('Отжимания — сегодня');
  });

  it('follows the card as its counter moves while the list is up', () => {
    const marks = { current: [markOf({ today_total: 50 })] };
    const { result, rerender } = renderHook(() => useTodayList([PUSH_UPS], marks.current));
    act(() => result.current.openMark(marks.current[0]));
    expect(result.current.mark?.today_total).toBe(50);

    marks.current = [markOf({ today_total: 25 })];
    rerender();

    expect(result.current.mark?.today_total).toBe(25);
  });

  it('still opens the sets of a card whose category is not among the active ones', () => {
    const mark = markOf({ category_id: 99, label: 'Старая отметка' });
    const { result } = renderHook(() => useTodayList([PUSH_UPS], [mark]));

    act(() => result.current.openMark(mark));

    expect(result.current.open).toBe(true);
    expect(result.current.category).toBeNull();
    expect(result.current.mark).toEqual(mark);
    expect(result.current.title).toBe('Старая отметка — сегодня');
  });

  it('closes, and a card opened afterwards does not inherit the last one', () => {
    const mark = markOf();
    const { result } = renderHook(() => useTodayList([PUSH_UPS, SQUATS], [mark]));
    act(() => result.current.openMark(mark));

    act(() => result.current.close());
    expect(result.current.open).toBe(false);

    act(() => result.current.openCategory(SQUATS));
    expect(result.current.mark).toBeNull();
    expect(result.current.category).toEqual(SQUATS);
  });

  it('closes by itself when the card it was opened from leaves the directory', () => {
    const marks = { current: [markOf()] };
    const { result, rerender } = renderHook(() => useTodayList([PUSH_UPS], marks.current));
    act(() => result.current.openMark(marks.current[0]));

    marks.current = [];
    rerender();

    expect(result.current.open).toBe(false);
  });
});
