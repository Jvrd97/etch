// [review:need-review] PHASE-01/201
// summary: tests the one-tap boolean avoid mark, its exact undo, failures, and the retained numeric form

import { afterEach, beforeEach, describe, expect, it, mock, spyOn } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import AvoidStreakCard from '@/components/AvoidStreakCard';
import { entriesAPI, type Category, type Entry, type Field } from '@/lib/api';
import { todayISO } from '@/lib/date';

const TIMESTAMP = '2026-09-10T10:00:00Z';
const DATE = todayISO();

const BOOLEAN_FIELD: Field = {
  id: 7, category_id: 1, name: 'Курение', field_type: 'boolean', is_required: false,
  order: 0, created_at: TIMESTAMP, updated_at: TIMESTAMP,
};
const NUMBER_FIELD: Field = {
  id: 8, category_id: 2, name: 'Сигареты', field_type: 'number', is_required: false,
  order: 0, created_at: TIMESTAMP, updated_at: TIMESTAMP,
};
const BOOLEAN_CATEGORY: Category = {
  id: 1, name: 'Не курить', display_mode: 'form', streak_mode: 'avoid', is_active: true,
  created_at: TIMESTAMP, updated_at: TIMESTAMP, fields: [BOOLEAN_FIELD],
};
const NUMBER_CATEGORY: Category = {
  id: 2, name: 'Меньше сигарет', display_mode: 'form', streak_mode: 'avoid', is_active: true,
  created_at: TIMESTAMP, updated_at: TIMESTAMP, fields: [NUMBER_FIELD],
};
const SAVED_BOOLEAN_ENTRY: Entry = {
  id: 11, category_id: BOOLEAN_CATEGORY.id, entry_date: DATE, created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  values: [{ id: 12, entry_id: 11, field_id: BOOLEAN_FIELD.id, value: 'true' }],
};

let create: ReturnType<typeof mock>;
let remove: ReturnType<typeof mock>;
let createSpy: ReturnType<typeof spyOn>;
let removeSpy: ReturnType<typeof spyOn>;

function renderCard(options?: {
  category?: Category;
  entries?: Entry[];
  onEntriesChanged?: ReturnType<typeof mock>;
}) {
  const onRelapse = mock(() => {});
  const onError = mock(() => {});
  const onEntriesChanged = options?.onEntriesChanged ?? mock(() => Promise.resolve());
  const view = render(
    <AvoidStreakCard
      category={options?.category ?? BOOLEAN_CATEGORY}
      numberField={options?.category === NUMBER_CATEGORY ? NUMBER_FIELD : undefined}
      entries={options?.entries ?? []}
      streak={{ category_id: options?.category?.id ?? BOOLEAN_CATEGORY.id, streak_mode: 'avoid', current_streak: 3, best_streak: 8, last_relapse_date: null }}
      onRelapse={onRelapse}
      onEntriesChanged={onEntriesChanged}
      onError={onError}
    />
  );
  return { onRelapse, onError, onEntriesChanged, view };
}

beforeEach(() => {
  create = mock(() => Promise.resolve(SAVED_BOOLEAN_ENTRY));
  remove = mock(() => Promise.resolve(undefined));
  createSpy = spyOn(entriesAPI, 'create').mockImplementation((payload, key) => create(payload, key));
  removeSpy = spyOn(entriesAPI, 'delete').mockImplementation((id) => remove(id));
});
afterEach(() => {
  createSpy.mockRestore();
  removeSpy.mockRestore();
  cleanup();
});

describe('AvoidStreakCard boolean avoid category', () => {
  it('saves true immediately and offers to undo only its own entry', async () => {
    const { onRelapse, onEntriesChanged } = renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0]).toEqual({ category_id: BOOLEAN_CATEGORY.id, entry_date: DATE, values: [{ field_id: BOOLEAN_FIELD.id, value: 'true' }] });
    expect(create.mock.calls[0][1]).toMatch(/^tap-/);
    expect(screen.getByRole('button', { name: 'Отменить' })).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith(SAVED_BOOLEAN_ENTRY.id));
    expect(screen.getByRole('button', { name: 'Случилось' })).toBeDefined();
    expect(onRelapse).toHaveBeenCalledTimes(2);
    expect(onEntriesChanged).toHaveBeenCalledTimes(2);
  });

  it('retries a failed boolean mark under the same idempotency key', async () => {
    const sentKeys: string[] = [];
    let attempts = 0;
    create = mock((_: unknown, idempotencyKey: string) => {
      sentKeys.push(idempotencyKey);
      attempts += 1;
      return attempts === 1
        ? Promise.reject(new Error('connection lost'))
        : Promise.resolve(SAVED_BOOLEAN_ENTRY);
    });
    const { onError } = renderCard();

    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отменить' })).toBeDefined());

    expect(create).toHaveBeenCalledTimes(2);
    expect(sentKeys[1]).toBe(sentKeys[0]);
  });

  it('reconciles an undo before a stale entry snapshot can show the mark again', async () => {
    const { onEntriesChanged, view } = renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отменить' })).toBeDefined());

    view.rerender(
      <AvoidStreakCard
        category={BOOLEAN_CATEGORY}
        numberField={undefined}
        entries={[SAVED_BOOLEAN_ENTRY]}
        streak={null}
        onRelapse={() => {}}
        onEntriesChanged={onEntriesChanged}
        onError={() => {}}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));

    await waitFor(() => expect(remove).toHaveBeenCalledWith(SAVED_BOOLEAN_ENTRY.id));
    expect(onEntriesChanged).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Случилось' })).toBeDefined();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('prevents a second click while the boolean mark is saving', async () => {
    let resolve: ((entry: Entry) => void) | undefined;
    create = mock(() => new Promise<Entry>((done) => { resolve = done; }));
    renderCard();
    const happened = screen.getByRole('button', { name: 'Случилось' });
    fireEvent.click(happened);
    fireEvent.click(happened);
    expect(create).toHaveBeenCalledTimes(1);
    expect((happened as HTMLButtonElement).disabled).toBe(true);
    resolve?.(SAVED_BOOLEAN_ENTRY);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отменить' })).toBeDefined());
  });

  it('restores the action and explains a save failure in Russian', async () => {
    create = mock(() => Promise.reject(new Error('network down')));
    const { onError } = renderCard();
    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Не удалось сохранить отметку'));
    expect(screen.getByRole('button', { name: 'Случилось' })).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Отменить' })).toBeNull();
  });

  it('does not treat false or an absent value as a confirmed happened state', () => {
    const falseEntry: Entry = { ...SAVED_BOOLEAN_ENTRY, values: [{ ...SAVED_BOOLEAN_ENTRY.values[0], value: 'false' }] };
    const { rerender } = render(<AvoidStreakCard category={BOOLEAN_CATEGORY} numberField={undefined} entries={[falseEntry]} streak={null} onRelapse={() => {}} onEntriesChanged={async () => {}} onError={() => {}} />);
    expect(screen.getByRole('button', { name: 'Случилось' })).toBeDefined();
    rerender(<AvoidStreakCard category={BOOLEAN_CATEGORY} numberField={undefined} entries={[]} streak={null} onRelapse={() => {}} onEntriesChanged={async () => {}} onError={() => {}} />);
    expect(screen.getByRole('button', { name: 'Случилось' })).toBeDefined();
  });

  it('restores a saved true fact from the day history without offering to delete it', () => {
    renderCard({ entries: [SAVED_BOOLEAN_ENTRY] });

    expect(screen.getByRole('status').textContent).toBe('Случилось');
    expect(screen.queryByRole('button', { name: 'Отменить' })).toBeNull();
  });

  it('keeps the number category form and sends its value', async () => {
    renderCard({ category: NUMBER_CATEGORY });
    fireEvent.click(screen.getByRole('button', { name: 'Случилось' }));
    fireEvent.change(screen.getByLabelText('Меньше сигарет: Сигареты'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0]).toEqual({ category_id: NUMBER_CATEGORY.id, entry_date: DATE, values: [{ field_id: NUMBER_FIELD.id, value: '2' }] });
  });
});
