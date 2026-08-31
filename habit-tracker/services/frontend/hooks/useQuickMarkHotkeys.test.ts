// [review:need-review] PHASE-03/122
// summary: tests for the Today keydown listener — the id a digit reports, the legend on "?", the silence while a field has focus, and the unmount that leaves the keyboard alone on every other screen

import { afterEach, describe, expect, it } from 'bun:test';
import { act, cleanup, renderHook } from '@testing-library/react';
import type { QuickMark } from '@/lib/api';
import { useQuickMarkHotkeys } from './useQuickMarkHotkeys';

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

const MARKS: QuickMark[] = [mark({ id: 11 }), mark({ id: 22, hotkey: 'p', label: 'Отжимания' })];

interface Spy {
  marked: number[];
  legends: number;
}

function mount(dialogOpen = false): { spy: Spy; unmount: () => void } {
  const spy: Spy = { marked: [], legends: 0 };
  const { unmount } = renderHook(() =>
    useQuickMarkHotkeys({
      marks: MARKS,
      dialogOpen,
      onMark: (id: number) => void spy.marked.push(id),
      onLegend: () => void (spy.legends += 1),
    })
  );
  return { spy, unmount };
}

/** Dispatch a real keydown the way a browser does, from a given target. */
function press(key: string, init: KeyboardEventInit = {}, target?: Element): void {
  act(() => {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
    (target ?? document.body).dispatchEvent(event);
  });
}

afterEach(() => {
  cleanup();
  document.body.innerHTML = '';
});

describe('useQuickMarkHotkeys', () => {
  it('marks the first button on "1", without a click anywhere', () => {
    const { spy } = mount();
    press('1');
    expect(spy.marked).toEqual([11]);
  });

  it('marks on the letter the button was given', () => {
    const { spy } = mount();
    press('p');
    expect(spy.marked).toEqual([22]);
  });

  it('marks on the physical key when the layout has changed', () => {
    const { spy } = mount();
    press('з', { code: 'KeyP' });
    expect(spy.marked).toEqual([22]);
  });

  it('shows the legend on "?"', () => {
    const { spy } = mount();
    press('?', { shiftKey: true });
    expect(spy.legends).toBe(1);
    expect(spy.marked).toEqual([]);
  });

  it('lets a focused field keep its keystrokes', () => {
    const { spy } = mount();
    const input = document.createElement('input');
    document.body.appendChild(input);
    press('1', {}, input);
    expect(spy.marked).toEqual([]);
  });

  it('consumes only the keystrokes it acts on', () => {
    mount();
    const acted = new KeyboardEvent('keydown', { key: '1', bubbles: true, cancelable: true });
    const ignored = new KeyboardEvent('keydown', { key: 'z', bubbles: true, cancelable: true });
    act(() => {
      document.body.dispatchEvent(acted);
      document.body.dispatchEvent(ignored);
    });
    expect(acted.defaultPrevented).toBe(true);
    expect(ignored.defaultPrevented).toBe(false);
  });

  it('says nothing while a dialog is up', () => {
    const { spy } = mount(true);
    press('1');
    expect(spy.marked).toEqual([]);
  });

  it('leaves the keyboard alone once the screen is gone', () => {
    const { spy, unmount } = mount();
    unmount();
    press('1');
    expect(spy.marked).toEqual([]);
  });
});
