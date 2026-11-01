// [review:need-review] PHASE-03/94, PHASE-03/221, PHASE-03/252, #311
// summary: #311 round 3 — a failed re-read of a week on screen keeps the week and says so above it
// summary: #252 — without a pinned day the squares are marked by the server's day
// summary: + the retro page links to the review of the same week
// summary: component tests for the week page — won days, the streak at its end and when the counters were taken are on the screen, the sunday checklist shows its ticks, and a week whose retro nobody wrote opens and says so instead of looking broken

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
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
let weekError: string | null = null;

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
  useWeek: () => ({ week: answer, loading: false, error: weekError, reload: () => {} }),
  LOAD_WEEK_ERROR: 'Не удалось загрузить неделю',
}));

const { default: WeekScreen, NO_RETRO_TEXT } = await import('./WeekScreen');
const api = await import('@/lib/api');

const TODAY = new Date(2026, 7, 30);

// The server's day, written onto the shared client and put back after each test, so
// whatever other suites left in the registry is not disturbed.
const agent = api.agentAPI as unknown as { dayMode?: () => Promise<unknown> };
const realDayMode = agent.dayMode;

function serverDayIs(date: string) {
  agent.dayMode = () => Promise.resolve({ date, kind: 'work', nocode: false, source: 'schedule' });
}

beforeEach(() => {
  answer = WEEK;
  weekError = null;
});

afterEach(() => {
  cleanup();
  agent.dayMode = realDayMode;
});

describe('WeekScreen', () => {
  it('keeps the mobile retro page inside /m when it links to the review', async () => {
    render(<WeekScreen iso="2026-W35" today={TODAY} compact />);

    await waitFor(() => expect(screen.getByText('Обзор недели →')).toBeDefined());
    expect(screen.getByText('Обзор недели →').closest('a')?.getAttribute('href')).toBe(
      '/m/week/review/2026-W35'
    );
  });

  it('links the retro page to the review of the same week', async () => {
    render(<WeekScreen iso="2026-W35" today={TODAY} />);

    await waitFor(() => expect(screen.getByText('Обзор недели →')).toBeDefined());
    expect(screen.getByText('Обзор недели →').closest('a')?.getAttribute('href')).toBe(
      '/week/review/2026-W35'
    );
  });

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

describe('WeekScreen day (#252)', () => {
  it('rings the server day and calls the days after it unlived, when no day is pinned', async () => {
    serverDayIs('2026-08-26');
    render(<WeekScreen iso="2026-W35" />);

    await waitFor(() =>
      expect(document.querySelector('[data-date="2026-08-26"]')?.className).toContain('ring-2')
    );
    expect(document.querySelector('[data-date="2026-08-25"]')?.getAttribute('data-status')).toBe('empty');
    expect(document.querySelector('[data-date="2026-08-27"]')?.getAttribute('data-status')).toBe('future');
  });
});

describe('WeekScreen: a failed re-read', () => {
  it('keeps the week on screen and says the re-read failed', () => {
    weekError = 'offline';
    render(<WeekScreen iso={WEEK.iso_code} today={TODAY} />);

    expect(screen.getByRole('heading', { level: 1 }).textContent).toContain(WEEK.iso_code);
    expect(within(screen.getByRole('alert')).getByText('offline')).toBeDefined();
  });
});
