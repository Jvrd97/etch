// [review:need-review] PHASE-03/94
// summary: component tests for the shared day navigation — days are grouped year → month, the month of the day being read is the one that opens, another month opens on a click, and every day is a link with its square in the right state

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { DayListItem } from '@/lib/api';

const DAYS: DayListItem[] = [
  { date: '2025-12-31', title: 'Прошлый год', verdict: 'won', done: 1, total: 1 },
  { date: '2026-07-31', title: 'Июль', verdict: 'lost', done: 0, total: 3 },
  { date: '2026-08-28', title: 'Пятница', verdict: 'won', done: 4, total: 4 },
  { date: '2026-08-30', title: 'Воскресенье', verdict: null, done: 0, total: 2 },
];

mock.module('@/hooks/useDays', () => ({
  useDays: () => ({ days: DAYS, loading: false, error: null, reload: () => {} }),
  LOAD_DAYS_ERROR: 'Не удалось загрузить дни',
}));

const { default: DaySidebar } = await import('./DaySidebar');

const TODAY = new Date(2026, 7, 30);

afterEach(() => {
  cleanup();
});

describe('DaySidebar', () => {
  it('groups the days year then month', () => {
    render(<DaySidebar today={TODAY} />);

    expect(screen.getByText('2026')).toBeDefined();
    expect(screen.getByText('2025')).toBeDefined();
    expect(screen.getByRole('button', { name: 'август' })).toBeDefined();
    expect(screen.getByRole('button', { name: 'июль' })).toBeDefined();
  });

  it('opens the month of the day being read, not the calendar month', () => {
    // Opening `/day/2026-07-31` and finding August expanded would answer a
    // question nobody asked.
    render(<DaySidebar activeDate="2026-07-31" today={TODAY} />);

    expect(screen.getByRole('button', { name: 'июль' }).getAttribute('aria-expanded')).toBe(
      'true'
    );
    expect(screen.getByRole('button', { name: 'август' }).getAttribute('aria-expanded')).toBe(
      'false'
    );
  });

  it('opens the current month when no day is named', () => {
    render(<DaySidebar today={TODAY} />);

    expect(screen.getByRole('button', { name: 'август' }).getAttribute('aria-expanded')).toBe(
      'true'
    );
  });

  it('opens another month on a click', () => {
    render(<DaySidebar today={TODAY} />);
    fireEvent.click(screen.getByRole('button', { name: 'июль' }));

    expect(screen.getByRole('button', { name: 'июль' }).getAttribute('aria-expanded')).toBe(
      'true'
    );
    expect(screen.getByText(/Июль/)).toBeDefined();
  });

  it('links every listed day and keeps its square in the right state', () => {
    render(<DaySidebar activeDate="2026-08-30" today={TODAY} />);

    const link = screen.getByRole('link', { name: /Воскресенье/ });
    expect(link.getAttribute('href')).toBe('/day/2026-08-30');
    expect(link.getAttribute('aria-current')).toBe('page');
    expect(
      document.querySelector('[data-date="2026-08-30"]')?.getAttribute('data-status')
    ).toBe('open');
  });
});
