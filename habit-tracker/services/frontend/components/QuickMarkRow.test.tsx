// [review:need-review] PHASE-03/121, PHASE-03/122, PHASE-03/124, PHASE-03/130, PHASE-01/206
// summary: tests for the quick-mark row — a button per directory row, the id the tap reports, the total drawn under the label, the done state, the key printed on the button only where a keyboard exists, the badge a button the plan names carries, the empty directory that renders no section at all, the undo affordance that appears only after a tap and names the button it takes back, and the card that opens the day's sets by its name and counter while its plus keeps adding one

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { QuickMark, QuickMarkEvent } from '@/lib/api';
import { PLANNED_BADGE } from '@/lib/quick-marks';

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

describe('QuickMarkRow undo', () => {
  const tapped: QuickMarkEvent = {
    event_id: 5,
    quick_mark_id: 1,
    entry_id: 42,
    entry_date: '2026-08-30',
    occurred_at: '2026-08-30T10:00:00Z',
    today_total: 250,
    done: true,
  };

  it('offers nothing to undo before a tap', () => {
    render(<QuickMarkRow marks={[mark()]} onTap={() => {}} onUndo={() => {}} />);

    expect(screen.queryByText(/Отменить/)).toBeNull();
  });

  it('names the button the offer would take back', () => {
    render(
      <QuickMarkRow
        marks={[mark()]}
        onTap={() => {}}
        lastEvent={tapped}
        onUndo={() => {}}
      />
    );

    expect(screen.getByText('Отменить «+250 мл»')).toBeTruthy();
  });

  it('takes the tap back in one action', () => {
    const onUndo = mock(() => {});
    render(
      <QuickMarkRow
        marks={[mark()]}
        onTap={() => {}}
        lastEvent={tapped}
        onUndo={onUndo}
      />
    );

    fireEvent.click(screen.getByText('Отменить «+250 мл»'));

    expect(onUndo).toHaveBeenCalledTimes(1);
  });

  it('offers nothing when the screen passes no undo at all', () => {
    render(<QuickMarkRow marks={[mark()]} onTap={() => {}} lastEvent={tapped} />);

    expect(screen.queryByText(/Отменить/)).toBeNull();
  });
});

describe('QuickMarkRow: a button the plan names', () => {
  it('badges the planned button and leaves the others plain', () => {
    // Порядок кнопку уже поднял, но «первая» — не признак: человек, впервые
    // открывший экран, не знает, каким список был вчера.
    render(
      <QuickMarkRow
        marks={[mark({ id: 1, planned: true, plan_item_id: 'item-1' }), mark({ id: 2 })]}
        onTap={(id: number) => onTap(id)}
      />
    );

    expect(screen.getAllByText(PLANNED_BADGE)).toHaveLength(1);
  });

  it('says "в плане на сегодня" to a reader who cannot see the badge', () => {
    render(
      <QuickMarkRow
        marks={[mark({ planned: true, plan_item_id: 'item-1' })]}
        onTap={(id: number) => onTap(id)}
      />
    );

    expect(
      screen.getByRole('button', { name: '+250 мл — в плане на сегодня' })
    ).toBeTruthy();
  });

  it('adds the plan to the done announcement rather than replacing it', () => {
    render(
      <QuickMarkRow
        marks={[mark({ planned: true, plan_item_id: 'item-1', done: true })]}
        onTap={(id: number) => onTap(id)}
      />
    );

    expect(
      screen.getByRole('button', { name: '+250 мл — в плане на сегодня — отмечено' })
    ).toBeTruthy();
  });
});

describe('QuickMarkRow: the way into the sets of the day', () => {
  it('stays one button per card while no screen asks for the list', () => {
    render(<QuickMarkRow marks={[mark()]} onTap={(id: number) => onTap(id)} />);

    expect(screen.getAllByRole('button')).toHaveLength(1);
  });

  it('splits a card in two when the screen can open the list', () => {
    render(
      <QuickMarkRow marks={[mark()]} onTap={(id: number) => onTap(id)} onOpen={() => {}} />
    );

    expect(screen.getAllByRole('button')).toHaveLength(2);
  });

  it('opens the list of the card by its name and counter, and adds nothing', () => {
    const onOpen = mock<(mark: QuickMark) => void>(() => {});
    render(
      <QuickMarkRow
        marks={[mark({ id: 7, label: 'Отжимания', today_total: 125, unit_label: null })]}
        onTap={(id: number) => onTap(id)}
        onOpen={onOpen}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Подходы за сегодня — Отжимания' }));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0].id).toBe(7);
    expect(onTap).not.toHaveBeenCalled();
  });

  it('keeps the plus adding one set, and never opens the list', () => {
    const onOpen = mock<(mark: QuickMark) => void>(() => {});
    render(
      <QuickMarkRow
        marks={[mark({ id: 7, label: 'Отжимания' })]}
        onTap={(id: number) => onTap(id)}
        onOpen={onOpen}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Отжимания' }));

    expect(onTap).toHaveBeenCalledTimes(1);
    expect(onTap.mock.calls[0][0]).toBe(7);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('keeps the counter inside the part that opens the list', () => {
    render(
      <QuickMarkRow
        marks={[mark({ today_total: 1250 })]}
        onTap={(id: number) => onTap(id)}
        onOpen={() => {}}
      />
    );

    const opener = screen.getByRole('button', { name: 'Подходы за сегодня — +250 мл' });
    expect(opener.textContent).toContain('1250 мл');
  });

  it('keeps the done state and the plan on the button that adds', () => {
    render(
      <QuickMarkRow
        marks={[mark({ planned: true, plan_item_id: 'item-1', done: true })]}
        onTap={(id: number) => onTap(id)}
        onOpen={() => {}}
      />
    );

    const plus = screen.getByRole('button', { name: '+250 мл — в плане на сегодня — отмечено' });
    expect(plus.getAttribute('aria-pressed')).toBe('true');
  });

  it('calls the list of a tick the marks of the day', () => {
    render(
      <QuickMarkRow
        marks={[mark({ kind: 'check', label: 'D3', unit_label: null })]}
        onTap={(id: number) => onTap(id)}
        onOpen={() => {}}
      />
    );

    expect(screen.getByRole('button', { name: 'Отметки за сегодня — D3' })).toBeDefined();
  });

  it('prints the key on the card where a keyboard exists, still out of the names', () => {
    const { container } = render(
      <QuickMarkRow
        marks={[mark({ hotkey: 'p', label: 'Отжимания' })]}
        onTap={(id: number) => onTap(id)}
        onOpen={() => {}}
        showHotkeys
      />
    );

    expect([...container.querySelectorAll('kbd')].map((node) => node.textContent)).toEqual(['p']);
    expect(screen.getByRole('button', { name: 'Отжимания' })).toBeDefined();
  });
});
