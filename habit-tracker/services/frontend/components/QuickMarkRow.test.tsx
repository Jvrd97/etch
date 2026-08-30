// [review:need-review] PHASE-03/121, PHASE-03/122
// summary: tests for the quick-mark row — a button per directory row, the id the tap reports, the total drawn under the label, the done state, the key printed on the button only where a keyboard exists, and the empty directory that renders no section at all

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { QuickMark } from '@/lib/api';

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

const { default: QuickMarkRow } = await import('./QuickMarkRow');

let onTap: ReturnType<typeof mock>;

beforeEach(() => {
  onTap = mock(() => {});
});

afterEach(() => {
  cleanup();
});

describe('QuickMarkRow', () => {
  it('renders one button per row of the directory', () => {
    render(
      <QuickMarkRow
        marks={[mark(), mark({ id: 2, label: 'D3', kind: 'check', unit_label: null })]}
        onTap={(id: number) => onTap(id)}
      />
    );
    expect(screen.getAllByRole('button')).toHaveLength(2);
  });

  it('reports the button id and nothing else', () => {
    render(<QuickMarkRow marks={[mark({ id: 7 })]} onTap={(id: number) => onTap(id)} />);
    fireEvent.click(screen.getByRole('button', { name: '+250 мл' }));
    expect(onTap).toHaveBeenCalledTimes(1);
    expect(onTap.mock.calls[0][0]).toBe(7);
  });

  it('draws the day total under the label', () => {
    render(
      <QuickMarkRow marks={[mark({ today_total: 1250 })]} onTap={(id: number) => onTap(id)} />
    );
    expect(screen.getByText('1250 мл')).toBeDefined();
  });

  it('says nothing where the day said nothing', () => {
    render(<QuickMarkRow marks={[mark()]} onTap={(id: number) => onTap(id)} />);
    expect(screen.queryByText('0 мл')).toBeNull();
  });

  it('marks a done button as pressed', () => {
    render(
      <QuickMarkRow
        marks={[mark({ kind: 'check', label: 'D3', unit_label: null, done: true })]}
        onTap={(id: number) => onTap(id)}
      />
    );
    const button = screen.getByRole('button', { name: 'D3 — отмечено' });
    expect(button.getAttribute('aria-pressed')).toBe('true');
  });

  it('prints the key on the button where a keyboard exists', () => {
    const { container } = render(
      <QuickMarkRow
        marks={[mark(), mark({ id: 2, label: 'Отжимания', hotkey: 'p' })]}
        onTap={(id: number) => onTap(id)}
        showHotkeys
      />
    );
    expect([...container.querySelectorAll('kbd')].map((node) => node.textContent)).toEqual([
      '1',
      'p',
    ]);
  });

  it('prints no key in the mobile shell, which has no keyboard', () => {
    const { container } = render(
      <QuickMarkRow marks={[mark({ hotkey: 'p' })]} onTap={(id: number) => onTap(id)} />
    );
    expect(container.querySelectorAll('kbd')).toHaveLength(0);
  });

  it('keeps the printed key out of what the button announces', () => {
    render(<QuickMarkRow marks={[mark()]} onTap={(id: number) => onTap(id)} showHotkeys />);
    // Still findable by the label alone: the key is drawn, not spoken.
    expect(screen.getByRole('button', { name: '+250 мл' })).toBeDefined();
  });

  it('renders no section at all for an empty directory', () => {
    const { container } = render(<QuickMarkRow marks={[]} onTap={(id: number) => onTap(id)} />);
    expect(container.firstChild).toBeNull();
  });
});
