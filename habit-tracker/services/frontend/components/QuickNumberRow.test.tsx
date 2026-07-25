// [review:need-review] PHASE-01/60-quick-plus-tap-adds-one
// summary: tests for QuickNumberRow — the "+" tap logs 1 with an empty field, the typed number otherwise, and never locks itself

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, Field } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';
const TODAY = '2026-07-24';

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

let createEntry: ReturnType<typeof mock>;

// Every mock of `@/lib/api` declares the whole surface the co-running suites link
// against, not just the members this file needs: bun fixes
// a module's export *names* the first time anything links against it and shares
// that registry across the run, so a partial mock here would delete `tableAPI`
// for whichever file loads later.
mock.module('@/lib/api', () => ({
  onboardingAPI: { draft: () => Promise.resolve({ operations: [] }) },
  insightsAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  categoriesAPI: {
    getAll: () => Promise.resolve([CATEGORY]),
    getById: () => Promise.resolve(CATEGORY),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(CATEGORY),
    update: () => Promise.resolve(CATEGORY),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: (data: unknown) => createEntry(data),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

mock.module('@/lib/date', () => ({ todayISO: () => TODAY }));

const { default: QuickNumberRow } = await import('./QuickNumberRow');

function renderRow(onError: (message: string) => void = () => {}) {
  render(
    <QuickNumberRow
      category={CATEGORY}
      numberField={GLASSES_FIELD}
      initialTotal={0}
      onError={onError}
    />
  );
  return {
    input: screen.getByLabelText('Water: add Glasses') as HTMLInputElement,
    plus: screen.getByRole('button', { name: 'Add to Water' }),
  };
}

/** The single value posted by the Nth create call. */
function postedValue(call: number): string {
  return (createEntry.mock.calls[call][0] as { values: { value: string }[] }).values[0].value;
}

beforeEach(() => {
  createEntry = mock(() => Promise.resolve(null));
});

afterEach(() => {
  cleanup();
});

describe('QuickNumberRow', () => {
  it('logs 1 when the field is empty, no keyboard involved', async () => {
    const { plus } = renderRow();

    fireEvent.click(plus);

    await waitFor(() => expect(createEntry).toHaveBeenCalledTimes(1));
    expect(createEntry.mock.calls[0][0]).toEqual({
      category_id: 1,
      entry_date: TODAY,
      values: [{ field_id: 7, value: '1' }],
    });
  });

  it('logs the typed number, then forgets it so the next tap is 1 again', async () => {
    const { input, plus } = renderRow();

    fireEvent.change(input, { target: { value: '250' } });
    fireEvent.click(plus);

    await waitFor(() => expect(createEntry).toHaveBeenCalledTimes(1));
    expect(postedValue(0)).toBe('250');
    await waitFor(() => expect(input.value).toBe(''));

    fireEvent.click(plus);
    await waitFor(() => expect(createEntry).toHaveBeenCalledTimes(2));
    expect(postedValue(1)).toBe('1');
  });

  it('adds the running total up as entries are logged', async () => {
    const { input, plus } = renderRow();

    fireEvent.change(input, { target: { value: '250' } });
    fireEvent.click(plus);

    await waitFor(() => expect(screen.getByText('250')).toBeDefined());
  });

  it('logs a negative number so a typo can be undone from the same row', async () => {
    const { input, plus } = renderRow();

    fireEvent.change(input, { target: { value: '-250' } });
    fireEvent.click(plus);

    await waitFor(() => expect(createEntry).toHaveBeenCalledTimes(1));
    expect(postedValue(0)).toBe('-250');
  });

  it('ignores a zero without creating an entry or shouting about it', async () => {
    const onError = mock(() => {});
    const { input, plus } = renderRow(onError);

    fireEvent.change(input, { target: { value: '0' } });
    fireEvent.click(plus);

    await waitFor(() => expect(input.value).toBe('0'));
    expect(createEntry).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it('ignores text the number input refused to parse instead of logging a 1', async () => {
    const onError = mock(() => {});
    const { input, plus } = renderRow(onError);

    // A real `type="number"` control blanks its `value` and raises `badInput` for
    // "abc"; happy-dom keeps the value but always reports `badInput: false`, so
    // the browser's verdict is what has to be stood in for here.
    fireEvent.change(input, { target: { value: '' } });
    Object.defineProperty(input, 'validity', {
      configurable: true,
      value: { badInput: true, valid: false },
    });

    fireEvent.click(plus);

    await waitFor(() => expect(onError).not.toHaveBeenCalled());
    expect(createEntry).not.toHaveBeenCalled();
  });

  it('sends one request per tap and never disables itself mid-flight', async () => {
    // Nothing ever resolves, so all five taps overlap: five deliberate
    // increments must not be collapsed into one by a "saving" lock.
    createEntry = mock(() => new Promise(() => {}));
    const { plus } = renderRow();

    for (let i = 0; i < 5; i += 1) {
      expect((plus as HTMLButtonElement).disabled).toBe(false);
      fireEvent.click(plus);
    }

    await waitFor(() => expect(createEntry).toHaveBeenCalledTimes(5));
    expect((plus as HTMLButtonElement).disabled).toBe(false);
  });

  it('reports a failed save and keeps the typed value for a retry', async () => {
    createEntry = mock(() => Promise.reject(new Error('server exploded')));
    const onError = mock(() => {});
    const { input, plus } = renderRow(onError);

    fireEvent.change(input, { target: { value: '250' } });
    fireEvent.click(plus);

    await waitFor(() => expect(onError).toHaveBeenCalledWith('server exploded'));
    expect(input.value).toBe('250');
  });
});
