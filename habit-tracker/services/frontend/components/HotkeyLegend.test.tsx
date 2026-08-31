// [review:need-review] PHASE-03/122
// summary: tests for the hotkey legend — a line per button with the key it answers to, a keyless button listed without a key, and the three ways out (Escape, the close button, the backdrop)

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { QuickMark } from '@/lib/api';

function mark(overrides: Partial<QuickMark> = {}): QuickMark {
  return {
    id: 1,
    label: 'Вода',
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

const { default: HotkeyLegend } = await import('./HotkeyLegend');

let onClose: ReturnType<typeof mock>;

beforeEach(() => {
  onClose = mock(() => {});
});

afterEach(() => {
  cleanup();
});

describe('HotkeyLegend', () => {
  it('lists key and label for every button', () => {
    render(
      <HotkeyLegend
        marks={[mark(), mark({ id: 2, label: 'Отжимания', hotkey: 'p' })]}
        onClose={() => onClose()}
      />
    );
    const keys = screen.getAllByText(/^[0-9a-z]$/);
    expect(keys.map((node) => node.textContent)).toEqual(['1', 'p']);
    expect(screen.getByText('Вода')).toBeDefined();
    expect(screen.getByText('Отжимания')).toBeDefined();
  });

  it('lists a keyless button without inventing a key for it', () => {
    // Ten buttons, none with a hotkey: the tenth is past the digits.
    const marks = Array.from({ length: 10 }, (_, i) =>
      mark({ id: i + 1, label: `Кнопка ${i + 1}` })
    );
    const { container } = render(<HotkeyLegend marks={marks} onClose={() => onClose()} />);
    expect(container.querySelectorAll('kbd')).toHaveLength(9);
    expect(screen.getByText('Кнопка 10')).toBeDefined();
    expect(screen.getByTitle('без клавиши')).toBeDefined();
  });

  it('closes on Escape', () => {
    render(<HotkeyLegend marks={[mark()]} onClose={() => onClose()} />);
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on its own button', () => {
    render(<HotkeyLegend marks={[mark()]} onClose={() => onClose()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('stays open on a click inside the sheet', () => {
    render(<HotkeyLegend marks={[mark()]} onClose={() => onClose()} />);
    fireEvent.click(screen.getByRole('dialog'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('stops listening for Escape once it is gone', () => {
    const { unmount } = render(<HotkeyLegend marks={[mark()]} onClose={() => onClose()} />);
    unmount();
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));
    });
    expect(onClose).not.toHaveBeenCalled();
  });
});
