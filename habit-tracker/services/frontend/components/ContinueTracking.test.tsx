// [review:need-review] #176
// summary: Continue tracking follows Today visibility and renders unit-aware add/editor actions

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { Category, Entry, Field } from '@/lib/api';
import { ContinueTracking } from './ContinueTracking';

const stamp = '2026-09-05T10:00:00Z';
const amount: Field = { id: 10, category_id: 1, name: 'Amount', field_type: 'number', is_required: false, order: 0, unit: 'ml', quick_steps: [250], created_at: stamp, updated_at: stamp };
const categories: Category[] = [
  { id: 1, name: 'Water', is_active: true, show_in_today: true, display_mode: 'form', streak_mode: 'build', fields: [amount], created_at: stamp, updated_at: stamp },
  { id: 2, name: 'Sleep', is_active: true, show_in_today: true, display_mode: 'form', streak_mode: 'build', fields: [], created_at: stamp, updated_at: stamp },
  { id: 3, name: 'Hidden', is_active: true, show_in_today: false, display_mode: 'form', streak_mode: 'build', fields: [{ ...amount, id: 30, category_id: 3 }], created_at: stamp, updated_at: stamp },
  { id: 4, name: 'Checklist', is_active: true, show_in_today: true, display_mode: 'checklist', streak_mode: 'build', fields: [{ ...amount, id: 40, category_id: 4, field_type: 'boolean' }], created_at: stamp, updated_at: stamp },
  { id: 5, name: 'Avoid', is_active: true, show_in_today: true, display_mode: 'form', streak_mode: 'avoid', fields: [], created_at: stamp, updated_at: stamp },
];
const entries: Entry[] = [
  { id: 5, category_id: 1, entry_date: '2026-09-04', created_at: stamp, updated_at: stamp, values: [{ id: 50, entry_id: 5, field_id: 10, value: '500' }] },
  { id: 6, category_id: 1, entry_date: '2026-09-05', created_at: stamp, updated_at: stamp, values: [] },
];

afterEach(cleanup);

describe('ContinueTracking', () => {
  it('renders configured cards in both shells with the correct action kind', () => {
    const { rerender } = render(<ContinueTracking categories={categories} entries={entries} />);
    expect(screen.getByText('Last: 500 ml')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Add Water entry' }).getAttribute('href')).toBe('/entries?new=1&category=1');
    expect(screen.getByRole('link', { name: 'Open Sleep editor' }).getAttribute('href')).toBe('/categories/2');
    expect(screen.queryByText('Hidden')).toBeNull();
    expect(screen.getByText('Checklist')).toBeTruthy();
    expect(screen.getByText('Avoid')).toBeTruthy();
    rerender(<ContinueTracking categories={categories} entries={entries} mobile />);
    expect(screen.getByRole('link', { name: 'Add Water entry' }).getAttribute('href')).toBe('/m/entries?new=1&category=1');
  });
});
