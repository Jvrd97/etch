// [review:need-review] PHASE-01/207
// summary: tests for the relapse block of the category page — streak numbers, week and month counts, average gap, trend wording, weekday split, the list of relapse days matching the server's dates, and the chart period switch

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import RelapseHistoryCard from '@/components/RelapseHistoryCard';
import type { RelapseHistory } from '@/lib/api';

// A Saturday.
const TODAY = '2026-10-24';

const HISTORY: RelapseHistory = {
  category_id: 1,
  streak_mode: 'avoid',
  current_streak: 4,
  best_streak: 21,
  last_relapse_date: '2026-10-20',
  tracked_since: '2026-08-01',
  // Gaps of 2, 9 and 40 days; three in the month before this one, one in this one.
  relapse_dates: ['2026-08-30', '2026-09-01', '2026-09-10', '2026-10-20'],
};

function term(name: string): string {
  const label = screen.getByText(name, { selector: 'dt' });
  return label.nextElementSibling?.textContent ?? '';
}

afterEach(() => {
  cleanup();
});

describe('RelapseHistoryCard', () => {
  it('shows the streak and the counts of the last week and month', () => {
    render(<RelapseHistoryCard history={HISTORY} today={TODAY} />);

    expect(screen.getByRole('heading', { name: 'Срывы' })).toBeDefined();
    expect(term('Текущая серия')).toBe('4 дня');
    expect(term('Лучшая серия')).toBe('21 день');
    expect(term('Последний срыв')).toBe('20 окт 2026');
    expect(term('Срывов за 7 дней')).toBe('1');
    expect(term('Срывов за 30 дней')).toBe('1');
    expect(term('Средний промежуток')).toBe('17 дней');
  });

  it('says the relapses got rarer than a month ago', () => {
    render(<RelapseHistoryCard history={HISTORY} today={TODAY} />);

    expect(screen.getByText('Реже, чем месяц назад: 1 против 3')).toBeDefined();
  });

  it('holds the trend back until the history is long enough', () => {
    render(
      <RelapseHistoryCard history={{ ...HISTORY, tracked_since: '2026-10-01' }} today={TODAY} />
    );

    expect(screen.getByText(/Тренд появится/)).toBeDefined();
  });

  it('splits the relapse days by weekday, Monday first', () => {
    render(<RelapseHistoryCard history={HISTORY} today={TODAY} />);

    const list = screen.getByRole('list', { name: 'Срывы по дням недели' });
    // 08-30 Sun, 09-01 Tue, 09-10 Thu, 10-20 Tue.
    expect(within(list).getAllByRole('listitem').map((item) => item.getAttribute('aria-label'))).toEqual([
      'Пн: 0', 'Вт: 2', 'Ср: 0', 'Чт: 1', 'Пт: 0', 'Сб: 0', 'Вс: 1',
    ]);
  });

  it('lists the relapse days the server returned, newest first', () => {
    render(<RelapseHistoryCard history={HISTORY} today={TODAY} />);

    const list = screen.getByRole('list', { name: 'Последние срывы' });
    expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      '20 окт 2026, Вт',
      '10 сен 2026, Чт',
      '1 сен 2026, Вт',
      '30 авг 2026, Вс',
    ]);
  });

  it('says there was nothing to break yet for a clean history', () => {
    render(
      <RelapseHistoryCard
        history={{ ...HISTORY, relapse_dates: [], last_relapse_date: null }}
        today={TODAY}
      />
    );

    expect(term('Последний срыв')).toBe('не было');
    expect(term('Средний промежуток')).toBe('—');
    expect(screen.getByText('Срывов не было')).toBeDefined();
  });

  it('switches the chart period and marks the chosen one', () => {
    render(<RelapseHistoryCard history={HISTORY} today={TODAY} />);
    const group = screen.getByRole('group', { name: 'Период графика срывов' });

    fireEvent.click(within(group).getByRole('button', { name: 'Год' }));

    expect(within(group).getByRole('button', { name: 'Год' }).getAttribute('aria-pressed')).toBe('true');
    expect(within(group).getByRole('button', { name: '90 дней' }).getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByRole('img', { name: /за год: 4 дня со срывом/ })).toBeDefined();
  });
});
