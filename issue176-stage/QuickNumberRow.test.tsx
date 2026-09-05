// [review:need-review] PHASE-01/63-today-card-tap-and-visibility, #176
// summary: QuickNumberRow tests include field-specific unit-labelled draft adjustments

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, Field } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';

const GLASSES_FIELD: Field = {
  id: 7,
  category_id: 1,
  name: 'Glasses',
  field_type: 'number',
  is_required: false,
  order: 1,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
};

const CATEGORY: Category = {
  id: 1,
  name: 'Water',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [GLASSES_FIELD],
};

const { default: QuickNumberRow } = await import('./QuickNumberRow');

let onAdd: ReturnType<typeof mock>;
let onOpenEditor: ReturnType<typeof mock>;

function renderRow(total = 0) {
  const view = render(
    <QuickNumberRow
      category={CATEGORY}
      numberField={GLASSES_FIELD}
      total={total}
      onAdd={(amount: number) => onAdd(amount)}
      onOpenEditor={() => onOpenEditor()}
    />
  );
  return {
    view,
    input: screen.getByLabelText('Water: add Glasses') as HTMLInputElement,
    plus: screen.getByRole('button', { name: 'Add to Water' }),
    card: screen.getByRole('button', { name: "Open today's Water entry" }),
  };
}

/** The amount handed to `onAdd` by the Nth tap. */
function addedAmount(call: number): number {
  return onAdd.mock.calls[call][0] as number;
}

beforeEach(() => {
  onAdd = mock(() => Promise.resolve(true));
  onOpenEditor = mock(() => {});
});

afterEach(() => {
  cleanup();
});

describe('QuickNumberRow', () => {
  it('wraps its controls on narrow screens', () => {
    const { view } = renderRow();
    expect(view.container.querySelector('form')?.className).toContain('flex-wrap');
  });
  it('configured quick step adjusts the draft and includes its unit', async () => {
    render(
      <QuickNumberRow
        category={CATEGORY}
        numberField={{ ...GLASSES_FIELD, unit: 'ml', quick_steps: [250] }}
        total={0}
        onAdd={(amount: number) => onAdd(amount)}
        onOpenEditor={() => onOpenEditor()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Adjust Water by +250 ml' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add to Water' }));
    await waitFor(() => expect(onAdd).toHaveBeenCalledWith(250));
  });
  it('adds 1 when the field is empty, no keyboard involved', async () => {
    const { plus } = renderRow();

    fireEvent.click(plus);

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(addedAmount(0)).toBe(1);
  });

  it('adds the typed number, then forgets it so the next tap is 1 again', async () => {
    const { input, plus } = renderRow();

    fireEvent.change(input, { target: { value: '250' } });
    fireEvent.click(plus);

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(addedAmount(0)).toBe(250);
    await waitFor(() => expect(input.value).toBe(''));

    fireEvent.click(plus);
    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(2));
    expect(addedAmount(1)).toBe(1);
  });

  it('shows the total it is given and holds none of its own', async () => {
    const { view } = renderRow(4);

    expect(screen.getByText('4')).toBeDefined();

    // The owner re-renders with the total recomputed from its entries; a row
    // that kept a private copy would still be showing 4 here.
    view.rerender(
      <QuickNumberRow
        category={CATEGORY}
        numberField={GLASSES_FIELD}
        total={9}
        onAdd={(amount: number) => onAdd(amount)}
        onOpenEditor={() => onOpenEditor()}
      />
    );

    expect(screen.getByText('9')).toBeDefined();
  });

  it('animates the total whenever it changes', () => {
    const { view } = renderRow(4);

    const before = screen.getByText('4');
    expect(before.className).toContain('animate-total-bump');

    view.rerender(
      <QuickNumberRow
        category={CATEGORY}
        numberField={GLASSES_FIELD}
        total={5}
        onAdd={(amount: number) => onAdd(amount)}
        onOpenEditor={() => onOpenEditor()}
      />
    );

    // Remounted rather than restyled: the same node would keep the finished
    // animation and the next tap would land silently.
    expect(screen.getByText('5')).not.toBe(before);
  });

  it('adds a negative number so a typo can be undone from the same row', async () => {
    const { input, plus } = renderRow();

    fireEvent.change(input, { target: { value: '-250' } });
    fireEvent.click(plus);

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(addedAmount(0)).toBe(-250);
  });

  it('ignores a zero without adding anything', async () => {
    const { input, plus } = renderRow();

    fireEvent.change(input, { target: { value: '0' } });
    fireEvent.click(plus);

    await waitFor(() => expect(input.value).toBe('0'));
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('ignores text the number input refused to parse instead of adding a 1', async () => {
    const { input, plus } = renderRow();

    // A real `type="number"` control blanks its `value` and raises `badInput` for
    // "abc"; happy-dom keeps the value but always reports `badInput: false`, so
    // the browser's verdict is what has to be stood in for here.
    fireEvent.change(input, { target: { value: '' } });
    Object.defineProperty(input, 'validity', {
      configurable: true,
      value: { badInput: true, valid: false },
    });

    fireEvent.click(plus);

    await waitFor(() => expect(input.validity.badInput).toBe(true));
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('sends one add per tap and never disables itself mid-flight', async () => {
    // Nothing ever resolves, so all five taps overlap: five deliberate
    // increments must not be collapsed into one by a "saving" lock.
    onAdd = mock(() => new Promise(() => {}));
    const { plus } = renderRow();

    for (let i = 0; i < 5; i += 1) {
      expect((plus as HTMLButtonElement).disabled).toBe(false);
      fireEvent.click(plus);
    }

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(5));
    expect((plus as HTMLButtonElement).disabled).toBe(false);
  });

  it('keeps the typed value for a retry when the save failed', async () => {
    onAdd = mock(() => Promise.resolve(false));
    const { input, plus } = renderRow();

    fireEvent.change(input, { target: { value: '250' } });
    fireEvent.click(plus);

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(input.value).toBe('250');
  });
});

describe('QuickNumberRow: the card tap', () => {
  it('opens the editor when the card itself is tapped', () => {
    const { card } = renderRow(3);

    fireEvent.click(card);

    expect(onOpenEditor).toHaveBeenCalledTimes(1);
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('does not open the editor on the "+"', async () => {
    const { plus } = renderRow();

    fireEvent.click(plus);

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(onOpenEditor).not.toHaveBeenCalled();
  });

  it('does not open the editor on the number input', () => {
    const { input } = renderRow();

    fireEvent.click(input);
    fireEvent.change(input, { target: { value: '2' } });

    expect(onOpenEditor).not.toHaveBeenCalled();
  });

  it('is the whole card for a pinned category with nothing to increment', () => {
    render(
      <QuickNumberRow
        category={CATEGORY}
        numberField={undefined}
        total={0}
        onAdd={(amount: number) => onAdd(amount)}
        onOpenEditor={() => onOpenEditor()}
      />
    );

    expect(screen.queryByRole('button', { name: 'Add to Water' })).toBeNull();
    expect(screen.queryByLabelText('Water: add Glasses')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: "Open today's Water entry" }));
    expect(onOpenEditor).toHaveBeenCalledTimes(1);
  });
});
