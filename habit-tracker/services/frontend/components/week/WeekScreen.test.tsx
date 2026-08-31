// [review:need-review] PHASE-03/94
// summary: component tests for the week page — won days, the streak at its end and when the counters were taken are on the screen, the sunday checklist shows its ticks, and a week whose retro nobody wrote opens and says so instead of looking broken

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import type { DayListItem, Week } from '@/lib/api';

const DAYS: DayListItem[] = [
  { date: '2026-08-28', title: 'Пятница', verdict: 'won', verdict_origin: 'computed', done: 4, total: 4 },
  { date: '2026-08-30', title: 'Воскресенье', verdict: null, verdict_origin: 'none', done: 0, total: 2 },
];

const WEEK: Week = {
  iso_code: '2026-W35',
  starts_on: '2026-08-24',
  ends_on: '2026-08-30',
  won_days: 1,
  total_days: 7,
  debt_minutes: 0,
  is_won: false,
  streak_end: 0,
  retro_md: '## Выигранные дни\n\n**1 из 7.**',
  blockers_md: 'День без отметок неотличим от дня без работы.',
  mgmt_retro_md: '',
  weekly_number_md: '',
  review_items: [
    { id: 'a', ord: 1, text_md: 'Решить: SQLite под отметки', done: true },
    { id: 'b', ord: 2, text_md: 'Петиция в ЕС, шаг 1', done: false },
  ],
  computed_at: '2026-08-30T18:00:00+00:00',
};

let answer: Week | null = WEEK;

mock.module('@/hooks/useDays', () => ({
  useDays: () => ({ days: DAYS, loading: false, error: null, reload: () => {} }),
  LOAD_DAYS_ERROR: 'Не удалось загрузить дни',
}));

// Сводка ролей подменяется на уровне хука, а не `@/lib/api`: подмена модуля в
// bun действует на весь прогон, и соседний набор тестов, подменивший `@/lib/api`
// без `rolesAPI`, ронял бы этот файл на импорте.
mock.module('@/hooks/useRoleSummary', () => ({
  useRoleSummary: () => ({ summary: null, loading: false, error: null }),
}));

mock.module('@/hooks/useWeek', () => ({
  useWeek: () => ({ week: answer, loading: false, error: null, reload: () => {} }),
  LOAD_WEEK_ERROR: 'Не удалось загрузить неделю',
}));

const { default: WeekScreen, NO_RETRO_TEXT } = await import('./WeekScreen');

const TODAY = new Date(2026, 7, 30);

beforeEach(() => {
  answer = WEEK;
});

afterEach(() => {
  cleanup();
});

describe('WeekScreen', () => {
  it('shows the won days, the streak at the end and when it was counted', async () => {
    render(<WeekScreen iso="2026-W35" today={TODAY} />);

    await waitFor(() => expect(screen.getByText('Выиграно дней')).toBeDefined());
    expect(screen.getByText('из 7')).toBeDefined();
    expect(screen.getByText('Стрик на конец')).toBeDefined();
    expect(screen.getByText('Счётчики сняты')).toBeDefined();
    expect(screen.getByText('2026-08-30 18:00')).toBeDefined();
  });

  it('shows the sunday checklist with what was closed and what was not', async () => {
    render(<WeekScreen iso="2026-W35" today={TODAY} />);

    await waitFor(() => expect(screen.getByText(/Решить: SQLite/)).toBeDefined());
    expect(screen.getByText('закрыт')).toBeDefined();
    expect(screen.getByText('не закрыт')).toBeDefined();
  });

  it('opens a week nobody wrote a retro for and says so', async () => {
    // The acceptance case: «неделя без написанного ретро существует и
    // открывается». Empty prose is a fact about the week, not a failed load.
    answer = { ...WEEK, retro_md: '', review_items: [] };
    render(<WeekScreen iso="2026-W40" today={TODAY} />);

    await waitFor(() => expect(screen.getByText(NO_RETRO_TEXT)).toBeDefined());
    expect(screen.getByText('Выиграно дней')).toBeDefined();
  });

  it('draws a square per day of the week, linked to that day', async () => {
    render(<WeekScreen iso="2026-W35" today={TODAY} />);

    await waitFor(() => expect(screen.getByText('Выиграно дней')).toBeDefined());
    expect(
      document.querySelector('[data-date="2026-08-28"]')?.getAttribute('href')
    ).toBe('/day/2026-08-28');
    expect(
      document.querySelector('[data-date="2026-08-30"]')?.getAttribute('data-status')
    ).toBe('open');
  });
});
