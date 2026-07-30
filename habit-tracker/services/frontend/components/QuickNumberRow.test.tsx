// [review:need-review] PHASE-01/61-today-total-owned-by-hook
// summary: tests for QuickNumberRow — it reports the amount to add and renders the total it is given, holding no total of its own

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

function renderRow(total = 0) {
  const view = render(
    <QuickNumberRow
      category={CATEGORY}
      numberField={GLASSES_FIELD}
      total={total}
      onAdd={(amount: number) => onAdd(amount)}
    />
  );
  return {
    view,
    input: screen.getByLabelText('Water: add Glasses') as HTMLInputElement,
    plus: screen.getByRole('button', { name: 'Add to Water' }),
  };
}

/** The amount handed to `onAdd` by the Nth tap. */
function addedAmount(call: number): number {
  return onAdd.mock.calls[call][0] as number;
}

beforeEach(() => {
  onAdd = mock(() => Promise.resolve(true));
});

afterEach(() => {
  cleanup();
});

describe('QuickNumberRow', () => {
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
