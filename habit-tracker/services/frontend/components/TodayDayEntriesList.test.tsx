// [review:need-review] PHASE-01/177, #176
// summary: tests the confirmed day-entry list, including optional field units

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { Category, Entry, Field } from '@/lib/api';
import TodayDayEntriesList from './TodayDayEntriesList';

const TIME = '2026-07-24T09:12:00Z';
const FIELD: Field = {
  id: 4, category_id: 1, name: 'Quantity', field_type: 'number', is_required: false,
  order: 0, created_at: TIME, updated_at: TIME,
};
const CATEGORY: Category = {
  id: 1, name: 'Bench press', display_mode: 'form', streak_mode: 'build', is_active: true,
  created_at: TIME, updated_at: TIME, fields: [FIELD],
};
const ENTRY: Entry = {
  id: 7, category_id: CATEGORY.id, entry_date: '2026-07-24', created_at: TIME,
  updated_at: TIME, values: [{ id: 8, entry_id: 7, field_id: FIELD.id, value: '2' }],
};

afterEach(cleanup);

describe('TodayDayEntriesList', () => {
  it('shows a row with its written time and values, then opens that exact row', () => {
    const onEdit = mock(() => {});
    render(<TodayDayEntriesList category={CATEGORY} entries={[ENTRY]} onEdit={onEdit} onDelete={async () => true} onAdd={() => {}} />);

    const localTime = new Intl.DateTimeFormat('en-GB', {
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(new Date(TIME));
    expect(screen.getByText(localTime)).toBeDefined();
    expect(screen.getByText('Quantity 2')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Edit entry 7' }));
    expect(onEdit).toHaveBeenCalledWith(ENTRY);
  });

  it('offers a fresh entry and deletes only the selected confirmed row', async () => {
    const onAdd = mock(() => {});
    const onDelete = mock(async () => true);
    render(<TodayDayEntriesList category={CATEGORY} entries={[ENTRY]} onEdit={() => {}} onDelete={onDelete} onAdd={onAdd} />);

    fireEvent.click(screen.getByRole('button', { name: 'Delete entry 7' }));
    expect(onDelete).toHaveBeenCalledWith(ENTRY);
    fireEvent.click(screen.getByRole('button', { name: 'Add entry' }));
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it('shows a numeric value with the unit owned by its field', () => {
    const category = {
      ...CATEGORY,
      fields: [{ ...FIELD, unit: 'kg' }],
    };

    render(
      <TodayDayEntriesList
        category={category}
        entries={[ENTRY]}
        onEdit={() => {}}
        onDelete={async () => true}
        onAdd={() => {}}
      />
    );

    expect(screen.getByText('Quantity 2 kg')).toBeDefined();
  });
});
