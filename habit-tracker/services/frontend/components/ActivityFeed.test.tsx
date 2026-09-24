// [review:need-review] #76
// summary: activity-feed rendering tests cover unit values, saved time for today, the day for older records and distinct journal rows

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { Category, Entry, JournalEntry } from '@/lib/api';
import { mergeActivityFeed } from '@/lib/activity-feed';
import { todayISO } from '@/lib/date';
import ActivityFeed from './ActivityFeed';

const timestamp = '2026-09-24T09:15:00Z';
// The dashboard labels a record of today by its time, so the fixture has to be
// dated today whenever the suite runs.
const today = todayISO();
const category: Category = {
  id: 1,
  name: 'Water',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: timestamp,
  updated_at: timestamp,
  fields: [{
    id: 2,
    category_id: 1,
    name: 'Amount',
    field_type: 'number',
    is_required: false,
    order: 1,
    unit: 'ml',
    created_at: timestamp,
    updated_at: timestamp,
  }],
};
const entry: Entry = {
  id: 123,
  category_id: 1,
  entry_date: today,
  created_at: timestamp,
  updated_at: timestamp,
  values: [{ id: 9, entry_id: 123, field_id: 2, value: '250' }],
};
const journal: JournalEntry = {
  id: 5,
  title: 'Day reflection',
  content: 'A good day',
  entry_date: today,
  created_at: '2026-09-24T10:15:00Z',
  updated_at: timestamp,
};

describe('ActivityFeed', () => {
  // The DOM is shared across the whole bun run; a render left behind leaks its
  // headings into whichever file queries the document next.
  afterEach(() => {
    cleanup();
  });

  it('shows category, value with unit, saved time and a distinct journal label without entry ids', () => {
    const { container } = render(
      <ActivityFeed items={mergeActivityFeed([entry], [journal])} categories={[category]} />
    );

    expect(screen.getByText('Water')).toBeDefined();
    expect(screen.getByText('Amount: 250 ml')).toBeDefined();
    expect(screen.getByText('Journal · Day reflection')).toBeDefined();
    expect(screen.getByText('A good day')).toBeDefined();
    expect(screen.queryByText(/Entry #123/)).toBeNull();
    expect(container.querySelector('time[datetime="2026-09-24T09:15:00Z"]')).not.toBeNull();
  });

  it('shows the day, not only the time, for a record of an earlier day', () => {
    const older: Entry = { ...entry, id: 124, entry_date: '2025-01-05' };
    const { container } = render(
      <ActivityFeed items={mergeActivityFeed([older], [])} categories={[category]} />
    );

    expect(screen.getByText('Jan 5, 2025')).toBeDefined();
    expect(container.querySelector('time[datetime="2025-01-05"]')).not.toBeNull();
  });

  it('groups by the day a record belongs to under a heading', () => {
    const older: Entry = { ...entry, id: 124, entry_date: '2025-01-05' };
    render(
      <ActivityFeed
        items={mergeActivityFeed([entry, older], [journal])}
        categories={[category]}
        grouped
      />
    );

    expect(
      screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)
    ).toEqual(['Today', 'Jan 5, 2025']);
  });
});
