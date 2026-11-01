// [review:need-review] PHASE-01/174, #311
// summary: CurrentStreaks tests the populated and empty dashboard states
import { describe, expect, it } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { CurrentStreaks, type AvoidStreak } from './CurrentStreaks';

const STREAKS: AvoidStreak[] = [
  {
    category: {
      id: 1,
      name: 'No Smoking',
      color: '#f00',
      display_mode: 'form',
      streak_mode: 'avoid',
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      fields: [],
    },
    streak: {
      category_id: 1,
      streak_mode: 'avoid',
      current_streak: 12,
      best_streak: 12,
      last_relapse_date: null,
    },
  },
];

describe('CurrentStreaks', () => {
  it('shows the active avoid category, day count and category list link', () => {
    render(<CurrentStreaks streaks={STREAKS} />);

    expect(screen.getByRole('heading', { name: 'Current streaks' })).toBeTruthy();
    expect(screen.getByText('No Smoking')).toBeTruthy();
    expect(screen.getByText('12 days')).toBeTruthy();
    expect(screen.getByRole('link', { name: /View all/i }).getAttribute('href')).toBe('/categories');
  });

  it('shows an empty state when no avoid category exists', () => {
    render(<CurrentStreaks streaks={[]} />);

    expect(screen.getByText('No avoid habits yet')).toBeTruthy();
  });
});
