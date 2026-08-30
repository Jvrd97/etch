// [review:need-review] PHASE-03/122
// summary: tests for the quick-mark hotkey decision — positional digits, a hotkey given by hand and the layout switch it survives, the silence demanded by a focused text field, a held modifier, a repeat and an open dialog, and the legend the assignment table produces

import { describe, expect, it } from 'bun:test';
import type { QuickMark } from '@/lib/api';
import {
  hotkeyAssignment,
  hotkeyLegendRows,
  resolveHotkey,
  type HotkeyEvent,
} from './quick-mark-hotkeys';

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
    ...overrides,
  };
}

/** `n` buttons with ids 1..n, none of them carrying a hotkey of its own. */
function directory(n: number): QuickMark[] {
  return Array.from({ length: n }, (_, i) => mark({ id: i + 1, label: `Кнопка ${i + 1}` }));
}

function press(key: string, overrides: Partial<HotkeyEvent> = {}): HotkeyEvent {
  return {
    key,
    code: '',
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    repeat: false,
    target: null,
    ...overrides,
  };
}

describe('resolveHotkey — positional digits', () => {
  it('marks the first button on "1"', () => {
    const marks = directory(3);
    expect(resolveHotkey(press('1'), { marks, dialogOpen: false })).toEqual({
      kind: 'mark',
      quickMarkId: 1,
    });
  });

  it('reaches the ninth button and stops there', () => {
    const marks = directory(12);
    expect(resolveHotkey(press('9'), { marks, dialogOpen: false })).toEqual({
      kind: 'mark',
      quickMarkId: 9,
    });
    // The tenth has neither a digit nor a hotkey: it is a mouse-only button.
    expect(hotkeyAssignment(marks)[9]).toBeNull();
  });

  it('says nothing for a digit past the end of the directory', () => {
    expect(resolveHotkey(press('4'), { marks: directory(2), dialogOpen: false })).toEqual({
      kind: 'none',
    });
  });

  it('says nothing for "0" — the digits start at one button, not at zero', () => {
    expect(resolveHotkey(press('0'), { marks: directory(3), dialogOpen: false })).toEqual({
      kind: 'none',
    });
  });
});

describe('resolveHotkey — a hotkey given by hand', () => {
  it('works exactly like a digit', () => {
    const marks = [mark({ id: 5 }), mark({ id: 6, hotkey: 'w' })];
    expect(resolveHotkey(press('w'), { marks, dialogOpen: false })).toEqual({
      kind: 'mark',
      quickMarkId: 6,
    });
  });

  it('answers to the key the user can press without Shift', () => {
    const marks = [mark({ id: 6, hotkey: 'W' })];
    expect(resolveHotkey(press('w'), { marks, dialogOpen: false })).toEqual({
      kind: 'mark',
      quickMarkId: 6,
    });
  });

  it('beats the position that digit would have had, and the loser shows no key', () => {
    const marks = [mark({ id: 1 }), mark({ id: 2 }), mark({ id: 3, hotkey: '2' })];
    expect(resolveHotkey(press('2'), { marks, dialogOpen: false })).toEqual({
      kind: 'mark',
      quickMarkId: 3,
    });
    expect(hotkeyAssignment(marks)).toEqual(['1', null, '2']);
  });

  it('survives a layout switch: the physical key still marks', () => {
    const marks = [mark({ id: 5 }), mark({ id: 6, hotkey: 'p', label: 'Отжимания' })];
    // Cyrillic layout: the `p` key types `з`, and `event.code` is what is left.
    expect(resolveHotkey(press('з', { code: 'KeyP' }), { marks, dialogOpen: false })).toEqual({
      kind: 'mark',
      quickMarkId: 6,
    });
  });

  it('lets the character actually typed win over the engraving', () => {
    // `з` is a hotkey in its own right here; the `p` sharing that plastic must
    // not steal the keystroke from it.
    const marks = [mark({ id: 5, hotkey: 'p' }), mark({ id: 6, hotkey: 'з' })];
    expect(resolveHotkey(press('з', { code: 'KeyP' }), { marks, dialogOpen: false })).toEqual({
      kind: 'mark',
      quickMarkId: 6,
    });
  });

  it('says nothing for a letter nobody asked for', () => {
    expect(resolveHotkey(press('q'), { marks: directory(3), dialogOpen: false })).toEqual({
      kind: 'none',
    });
  });

  it('ignores named keys outright', () => {
    for (const key of ['Enter', 'ArrowDown', 'Escape', 'Tab']) {
      expect(resolveHotkey(press(key), { marks: directory(3), dialogOpen: false })).toEqual({
        kind: 'none',
      });
    }
  });
});

describe('resolveHotkey — when the keyboard is not ours', () => {
  const marks = directory(3);

  it('stays silent while the user types into a field', () => {
    for (const tagName of ['INPUT', 'TEXTAREA', 'SELECT']) {
      expect(resolveHotkey(press('1', { target: { tagName } }), { marks, dialogOpen: false })).toEqual(
        { kind: 'none' }
      );
    }
  });

  it('stays silent inside a contenteditable', () => {
    const target = { tagName: 'DIV', isContentEditable: true };
    expect(resolveHotkey(press('2', { target }), { marks, dialogOpen: false })).toEqual({
      kind: 'none',
    });
  });

  it('still fires on a plain element that takes no text', () => {
    const target = { tagName: 'DIV', isContentEditable: false };
    expect(resolveHotkey(press('2', { target }), { marks, dialogOpen: false })).toEqual({
      kind: 'mark',
      quickMarkId: 2,
    });
  });

  it('leaves Cmd+1, Ctrl+1 and Alt+1 to the browser', () => {
    for (const held of [{ metaKey: true }, { ctrlKey: true }, { altKey: true }]) {
      expect(resolveHotkey(press('1', held), { marks, dialogOpen: false })).toEqual({
        kind: 'none',
      });
    }
  });

  it('treats a shifted key as a different keystroke', () => {
    expect(resolveHotkey(press('!', { shiftKey: true }), { marks, dialogOpen: false })).toEqual({
      kind: 'none',
    });
  });

  it('ignores a key held down', () => {
    expect(resolveHotkey(press('1', { repeat: true }), { marks, dialogOpen: false })).toEqual({
      kind: 'none',
    });
  });

  it('hands the keyboard to an open dialog', () => {
    expect(resolveHotkey(press('1'), { marks, dialogOpen: true })).toEqual({ kind: 'none' });
    expect(resolveHotkey(press('?', { shiftKey: true }), { marks, dialogOpen: true })).toEqual({
      kind: 'none',
    });
  });
});

describe('resolveHotkey — the legend', () => {
  const marks = directory(3);

  it('opens on "?", Shift and all', () => {
    expect(resolveHotkey(press('?', { shiftKey: true }), { marks, dialogOpen: false })).toEqual({
      kind: 'legend',
    });
  });

  it('opens on a layout where "?" needs no Shift', () => {
    expect(resolveHotkey(press('?'), { marks, dialogOpen: false })).toEqual({ kind: 'legend' });
  });

  it('stays shut under Cmd', () => {
    expect(
      resolveHotkey(press('?', { shiftKey: true, metaKey: true }), { marks, dialogOpen: false })
    ).toEqual({ kind: 'none' });
  });

  it('stays shut while the user is typing a question mark', () => {
    expect(
      resolveHotkey(press('?', { shiftKey: true, target: { tagName: 'TEXTAREA' } }), {
        marks,
        dialogOpen: false,
      })
    ).toEqual({ kind: 'none' });
  });

  it('has nothing to explain when the directory is empty', () => {
    expect(resolveHotkey(press('?'), { marks: [], dialogOpen: false })).toEqual({ kind: 'none' });
  });
});

describe('hotkeyLegendRows', () => {
  it('lists every button, with the key it answers to', () => {
    const marks = [mark({ id: 1, label: 'Вода' }), mark({ id: 2, label: 'Отжимания', hotkey: 'p' })];
    expect(hotkeyLegendRows(marks)).toEqual([
      { quickMarkId: 1, label: 'Вода', key: '1' },
      { quickMarkId: 2, label: 'Отжимания', key: 'p' },
    ]);
  });

  it('lists a keyless button without inventing a key for it', () => {
    const rows = hotkeyLegendRows(directory(10));
    expect(rows).toHaveLength(10);
    expect(rows[9].key).toBeNull();
  });
});
