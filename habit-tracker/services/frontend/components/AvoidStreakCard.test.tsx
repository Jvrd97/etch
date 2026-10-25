// [review:need-review] PHASE-01/201, PHASE-01/207
// summary: tests the one-tap «Случилось» of every avoid category through the relapse endpoint (no form), its exact undo (never of a relapse it did not write), the details added afterwards, failures that leave the counter alone, the retry under the same key, and the card's link into the category page of the current shell

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  categoriesAPI,
  entriesAPI,
  type Category,
  type Entry,
  type EntryCreate,
  type Field,
  type RelapseRecorded,
} from '@/lib/api';

let pathname = '/today';
mock.module('next/navigation', () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push: () => {}, replace: () => {} }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

const { default: AvoidStreakCard } = await import('@/components/AvoidStreakCard');

const TIMESTAMP = '2026-09-10T10:00:00Z';
const DATE = '2026-09-10';

function field(id: number, categoryId: number, name: string, fieldType: Field['field_type'], order = 0): Field {
  return {
    id, category_id: categoryId, name, field_type: fieldType, is_required: false,
    order, created_at: TIMESTAMP, updated_at: TIMESTAMP,
  };
}

function category(id: number, name: string, fields: Field[]): Category {
  return {
    id, name, display_mode: 'form', streak_mode: 'avoid', is_active: true,
    created_at: TIMESTAMP, updated_at: TIMESTAMP, fields,
  };
}

const BOOLEAN_FIELD = field(7, 1, 'Курил', 'boolean');
const BOOLEAN_CATEGORY = category(1, 'Не курить', [BOOLEAN_FIELD]);
const CIGARETTES_FIELD = field(8, 2, 'Сигареты', 'number');
const COMPOSITE_CATEGORY = category(2, 'Меньше сигарет', [
  field(9, 2, 'Курил', 'boolean', 0),
  CIGARETTES_FIELD,
  field(10, 2, 'Что курил', 'text', 2),
]);

// Every shape the ticket names: the card must not care which one it got.
const FIELD_SETS: Array<[string, Category]> = [
  ['boolean', BOOLEAN_CATEGORY],
  ['boolean + text', category(3, 'Пиво', [field(11, 3, 'Пил', 'boolean'), field(12, 3, 'Что', 'text', 1)])],
  ['two booleans', category(4, 'Алкоголь', [field(13, 4, 'Пиво', 'boolean'), field(14, 4, 'Вино', 'boolean', 1)])],
  ['number', category(5, 'Сладкое', [field(15, 5, 'Штук', 'number')])],
  ['text only', category(6, 'Ругань', [field(16, 6, 'Что сказал', 'text')])],
  ['duration', category(7, 'Соцсети', [field(17, 7, 'Сколько', 'duration')])],
];

function relapseEntry(categoryId: number, values: RelapseRecorded['values'] = [], created = true): RelapseRecorded {
  return { id: 41, category_id: categoryId, entry_date: DATE, created_at: TIMESTAMP, updated_at: TIMESTAMP, values, created };
}

const STREAK = { category_id: 1, streak_mode: 'avoid' as const, current_streak: 3, best_streak: 8, last_relapse_date: null };

let recordRelapse: ReturnType<typeof mock>;
let update: ReturnType<typeof mock>;
let remove: ReturnType<typeof mock>;
let create: ReturnType<typeof mock>;
const restores: Array<() => void> = [];

/**
 * Swap one method of an API object for the test and remember how to put it back.
 *
 * Assignment rather than `spyOn`: another suite may have replaced '@/lib/api'
 * process-wide with a mock whose `categoriesAPI` has no `recordRelapse` yet, and
 * `spyOn` refuses a property that is not there.
 */
function stub<T extends object, K extends keyof T>(target: T, key: K, implementation: T[K]): void {
  const original = target[key];
  target[key] = implementation;
  restores.push(() => {
    target[key] = original;
  });
}

function renderCard(options?: { category?: Category; numberField?: Field }) {
  const onRelapse = mock(() => Promise.resolve());
  const onError = mock(() => {});
  const onEntriesChanged = mock(() => Promise.resolve());
  render(
    <AvoidStreakCard
      category={options?.category ?? BOOLEAN_CATEGORY}
      numberField={options?.numberField}
      streak={STREAK}
      onRelapse={onRelapse}
      onEntriesChanged={onEntriesChanged}
      onError={onError}
    />
  );
  return { onRelapse, onError, onEntriesChanged };
}

beforeEach(() => {
  pathname = '/today';
  recordRelapse = mock((categoryId: number) =>
    Promise.resolve(relapseEntry(categoryId, [{ id: 51, entry_id: 41, field_id: 9, value: 'true' }]))
  );
  update = mock((id: number, data: Partial<Entry>) => Promise.resolve({ ...relapseEntry(2), id, ...data }));
  remove = mock(() => Promise.resolve(undefined));
  create = mock(() => Promise.reject(new Error('the card must not create entries itself')));
  stub(categoriesAPI, 'recordRelapse', (id: number, key?: string) => recordRelapse(id, key));
  stub(entriesAPI, 'update', (id: number, data: Partial<EntryCreate>) => update(id, data));
  stub(entriesAPI, 'delete', (id: number) => remove(id));
  stub(entriesAPI, 'create', (payload: EntryCreate, key?: string) => create(payload, key));
});
afterEach(() => {
  while (restores.length > 0) restores.pop()?.();
  cleanup();
});

describe('AvoidStreakCard «Случилось»', () => {
  for (const [shape, avoidCategory] of FIELD_SETS) {
    it(`records a relapse in one tap for a ${shape} category, without a form`, async () => {
      const { onRelapse, onEntriesChanged } = renderCard({ category: avoidCategory });

      fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));

      await waitFor(() => expect(onEntriesChanged).toHaveBeenCalledTimes(1));
      expect(recordRelapse).toHaveBeenCalledTimes(1);
      expect(recordRelapse.mock.calls[0][0]).toBe(avoidCategory.id);
      expect(recordRelapse.mock.calls[0][1]).toMatch(/^tap-/);
      expect(create).not.toHaveBeenCalled();
      expect(onRelapse).toHaveBeenCalledWith(avoidCategory.id);
      expect(screen.queryByRole('textbox')).toBeNull();
      expect(screen.getByRole('status').textContent).toBe('Срыв записан');
    });
  }

  it('refreshes the streak before the day list, so the counter drops first', async () => {
    const order: string[] = [];
    const onRelapse = mock(() => {
      order.push('streak');
      return Promise.resolve();
    });
    const onEntriesChanged = mock(() => {
      order.push('entries');
      return Promise.resolve();
    });
    render(
      <AvoidStreakCard category={BOOLEAN_CATEGORY} streak={STREAK} onRelapse={onRelapse} onEntriesChanged={onEntriesChanged} onError={() => {}} />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));

    await waitFor(() => expect(order).toEqual(['streak', 'entries']));
  });

  it('undoes exactly the relapse it recorded', async () => {
    const { onRelapse, onEntriesChanged } = renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отменить' })).toBeDefined());

    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith(41));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Отменить' })).toBeNull());
    expect(screen.queryByRole('status')).toBeNull();
    expect(onRelapse).toHaveBeenCalledTimes(2);
    expect(onEntriesChanged).toHaveBeenCalledTimes(2);
  });

  it('does not offer to undo a relapse somebody else already recorded today', async () => {
    recordRelapse = mock(() => Promise.resolve(relapseEntry(1, [], false)));
    const { onRelapse } = renderCard();

    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Срыв уже записан'));
    expect(screen.queryByRole('button', { name: 'Отменить' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Подробнее' })).toBeDefined();
    expect(onRelapse).toHaveBeenCalledWith(1);
  });

  it('shows a failed tap and leaves the counter alone, then retries under the same key', async () => {
    let attempts = 0;
    recordRelapse = mock(() => {
      attempts += 1;
      return attempts === 1 ? Promise.reject(new Error('connection lost')) : Promise.resolve(relapseEntry(1));
    });
    const { onError, onRelapse } = renderCard();

    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Не удалось записать срыв'));
    expect(onRelapse).not.toHaveBeenCalled();
    expect(screen.getByText('3 days clean')).toBeDefined();
    expect(screen.queryByRole('status')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Срыв записан'));
    expect(recordRelapse.mock.calls[1][1]).toBe(recordRelapse.mock.calls[0][1]);
  });

  it('sends one request however fast the button is pressed twice', async () => {
    let resolve: ((entry: RelapseRecorded) => void) | undefined;
    recordRelapse = mock(() => new Promise<RelapseRecorded>((done) => { resolve = done; }));
    renderCard();
    const happened = screen.getByRole('button', { name: 'Случилось' });

    fireEvent.click(happened);
    fireEvent.click(happened);

    expect(recordRelapse).toHaveBeenCalledTimes(1);
    expect((happened as HTMLButtonElement).disabled).toBe(true);
    resolve?.(relapseEntry(1));
    await waitFor(() => expect(screen.getByRole('status')).toBeDefined());
  });

  it('a new tap after a recorded one is another relapse under a fresh key', async () => {
    renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(screen.getByRole('status')).toBeDefined());

    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));

    await waitFor(() => expect(recordRelapse).toHaveBeenCalledTimes(2));
    expect(recordRelapse.mock.calls[1][1]).not.toBe(recordRelapse.mock.calls[0][1]);
  });
});

describe('AvoidStreakCard details after the tap', () => {
  it('adds how many and a note to the recorded entry, keeping what the server wrote', async () => {
    const { onRelapse, onEntriesChanged } = renderCard({ category: COMPOSITE_CATEGORY, numberField: CIGARETTES_FIELD });
    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подробнее' })).toBeDefined());

    fireEvent.click(screen.getByRole('button', { name: 'Подробнее' }));
    fireEvent.change(screen.getByLabelText('Сигареты'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Заметка'), { target: { value: ' после кофе ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update.mock.calls[0]).toEqual([
      41,
      { notes: 'после кофе', values: [{ field_id: 9, value: 'true' }, { field_id: CIGARETTES_FIELD.id, value: '3' }] },
    ]);
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeNull());
    expect(onRelapse).toHaveBeenCalledTimes(2);
    expect(onEntriesChanged).toHaveBeenCalledTimes(2);
  });

  it('offers a note alone when the category counts nothing', async () => {
    const textOnly = FIELD_SETS[4][1];
    recordRelapse = mock(() => Promise.resolve(relapseEntry(textOnly.id)));
    renderCard({ category: textOnly });
    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подробнее' })).toBeDefined());

    fireEvent.click(screen.getByRole('button', { name: 'Подробнее' }));
    fireEvent.change(screen.getByLabelText('Заметка'), { target: { value: 'на работе' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(update).toHaveBeenCalledWith(41, { notes: 'на работе' }));
  });

  it('keeps the details open and says so when saving them fails', async () => {
    update = mock(() => Promise.reject(new Error('server down')));
    const { onError } = renderCard({ category: COMPOSITE_CATEGORY, numberField: CIGARETTES_FIELD });
    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Подробнее' })).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: 'Подробнее' }));
    fireEvent.change(screen.getByLabelText('Сигареты'), { target: { value: '2' } });

    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

    await waitFor(() => expect(onError).toHaveBeenCalledWith('Не удалось сохранить подробности'));
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDefined();
  });
});

describe('AvoidStreakCard link to the category page', () => {
  it('opens the desktop category page from /today', () => {
    renderCard();

    const link = screen.getByRole('link', { name: 'Не курить: история срывов' });

    expect(link.getAttribute('href')).toBe('/categories/1');
  });

  it('stays inside the mobile shell from /m/today', () => {
    pathname = '/m/today';
    renderCard();

    const link = screen.getByRole('link', { name: 'Не курить: история срывов' });

    expect(link.getAttribute('href')).toBe('/m/categories/1');
  });
});
