// [review:need-review] PHASE-03/94, PHASE-03/252
// summary: #252 — without a pinned day the month view stands on the server's day and marks it
// summary: component tests for the timeline — the five views switch, the weeks-left counter is on the screen, a square carries the state of its day and links to it, and stepping down from the week view lands on the day it names

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { DayListItem } from '@/lib/api';

const DAYS: DayListItem[] = [
  { date: '2026-08-28', title: 'Пятница', verdict: 'won', verdict_origin: 'computed', done: 4, total: 4 },
  { date: '2026-08-29', title: 'Суббота', verdict: 'lost', verdict_origin: 'computed', done: 0, total: 4 },
  { date: '2026-08-30', title: 'Воскресенье', verdict: null, verdict_origin: 'none', done: 0, total: 2 },
];

mock.module('@/hooks/useDays', () => ({
  useDays: () => ({ days: DAYS, loading: false, error: null, reload: () => {} }),
  LOAD_DAYS_ERROR: 'Не удалось загрузить дни',
}));

const { default: LifeGrid, VIEW_LABEL } = await import('./LifeGrid');
const api = await import('@/lib/api');

const TODAY = new Date(2026, 7, 30);

// The server's day, written onto the shared client and put back after each test, so
// whatever other suites left in the registry is not disturbed.
const agent = api.agentAPI as unknown as { dayMode?: () => Promise<unknown> };
const realDayMode = agent.dayMode;

function serverDayIs(date: string) {
  agent.dayMode = () => Promise.resolve({ date, kind: 'work', nocode: false, source: 'schedule' });
}

function show() {
  render(<LifeGrid today={TODAY} />);
}

function switchTo(view: keyof typeof VIEW_LABEL) {
  fireEvent.click(screen.getByRole('button', { name: VIEW_LABEL[view] }));
}

afterEach(() => {
  cleanup();
  agent.dayMode = realDayMode;
});

describe('LifeGrid', () => {
  it('shows the weeks-left counter', () => {
    show();

    expect(screen.getByText('Осталось недель')).toBeDefined();
    expect(screen.getByText('Прожито недель')).toBeDefined();
  });

  it('opens on the life view and switches through all five', () => {
    // The acceptance case: жизнь → год → месяц → неделя → день.
    show();
    expect(screen.getByLabelText(`Вид: ${VIEW_LABEL.life}`)).toBeDefined();

    for (const view of ['year', 'month', 'week', 'day'] as const) {
      switchTo(view);
      expect(screen.getByLabelText(`Вид: ${VIEW_LABEL[view]}`)).toBeDefined();
    }
  });

  it('paints a day nobody closed differently from a day that was lost', () => {
    show();
    switchTo('month');

    const lost = document.querySelector('[data-date="2026-08-29"]');
    const open = document.querySelector('[data-date="2026-08-30"]');

    expect(lost?.getAttribute('data-status')).toBe('lost');
    expect(open?.getAttribute('data-status')).toBe('open');
  });

  it('opens the day screen from a square', () => {
    show();
    switchTo('month');

    const square = document.querySelector('[data-date="2026-08-28"]');

    expect(square?.getAttribute('href')).toBe('/day/2026-08-28');
  });

  it('offers the week page from the week view', () => {
    show();
    switchTo('week');

    expect(screen.getByText(/Открыть неделю 2026-W35/)).toBeDefined();
  });

  it('steps from a day of the week view into the day view', () => {
    show();
    switchTo('week');
    fireEvent.click(screen.getByRole('button', { name: /^пт 28$/ }));

    expect(screen.getByLabelText(`Вид: ${VIEW_LABEL.day}`)).toBeDefined();
    expect(screen.getByText('2026-08-28')).toBeDefined();
  });
});

describe('LifeGrid day (#252)', () => {
  it('stands the month view on the server day and rings it, when no day is pinned', async () => {
    serverDayIs('2026-08-26');
    render(<LifeGrid />);
    switchTo('month');

    await waitFor(() => expect(document.querySelector('[data-date="2026-08-26"]')).not.toBeNull());
    expect(document.querySelector('[data-date="2026-08-26"]')?.className).toContain('ring-2');
    // Behind the server's day a day nobody wrote is empty, ahead of it the frame is unlived.
    expect(document.querySelector('[data-date="2026-08-25"]')?.getAttribute('data-status')).toBe('empty');
    expect(document.querySelector('[data-date="2026-08-27"]')?.getAttribute('data-status')).toBe('future');
  });
});
