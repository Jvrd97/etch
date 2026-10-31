// [review:need-review] PHASE-03/221, PHASE-03/239, PHASE-03/255, PHASE-03/244
// summary: component tests for the week review screen — totals with their signed changes, the best and worst day named in words, an unfinished week announced and compared by days, a missing sleep metric said as missing, an empty week without the narrative button, and the narrative written on request and refused with its own message

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { WeekNarrative, WeekReview } from '@/lib/api';
import type { WeekReviewClient } from '@/hooks/useWeekReview';
import { adherenceFixture, weekReviewFixture } from '@/components/week-review/test-fixture';

const { default: WeekReviewScreen, NARRATIVE_BUTTON } = await import('./WeekReviewScreen');
const { ROLES_RUNNING_WEEK_NOTE } = await import('@/lib/week-review');

afterEach(() => {
  cleanup();
});

function clientOf(
  review: WeekReview,
  narrative: () => Promise<WeekNarrative> = () =>
    Promise.resolve({ iso_code: review.window.iso_code, text: 'Неделя прошла ровно.', model: 'm' })
): WeekReviewClient & { narrate: ReturnType<typeof mock> } {
  const narrate = mock(narrative);
  return {
    get: () => Promise.resolve(review),
    narrative: () => narrate(),
    narrate,
  };
}

async function ready(review: WeekReview, compact = false) {
  const client = clientOf(review);
  render(<WeekReviewScreen iso="2026-W35" compact={compact} client={client} />);
  await waitFor(() => expect(screen.getByText('Итог недели')).toBeDefined());
  return client;
}

describe('WeekReviewScreen', () => {
  it('shows the totals with the sign of each change', async () => {
    await ready(weekReviewFixture());

    expect(screen.getByText('Выиграно дней')).toBeDefined();
    expect(screen.getByText('из 3')).toBeDefined();
    expect(screen.getByText('+1')).toBeDefined();
    expect(screen.getByText('67%')).toBeDefined();
    expect(screen.getByText('+29 п.п.')).toBeDefined();
    expect(screen.getByText('20 ч')).toBeDefined();
  });

  it('names the best and the worst day in words, not only in colour', async () => {
    await ready(weekReviewFixture());

    expect(screen.getByText('лучший')).toBeDefined();
    expect(screen.getByText('худший')).toBeDefined();
  });

  it('prints the day streak and the roles with their time against the last week', async () => {
    await ready(weekReviewFixture());

    expect(screen.getByText('Тимлид')).toBeDefined();
    expect(screen.getByText('5 ч · 75%', { exact: false })).toBeDefined();
    // The role with no minutes either week is not a row.
    expect(screen.queryByText('Архитектор')).toBeNull();
    expect(screen.getByText('Курение')).toBeDefined();
    expect(screen.getByText('1 срыв за неделю')).toBeDefined();
  });

  it('says the sleep metric is not connected instead of printing zero hours', async () => {
    await ready(weekReviewFixture());

    expect(screen.getByText('Метрика не подключена')).toBeDefined();
    expect(screen.getByText('Шаги')).toBeDefined();
  });

  it('announces an unfinished week and says what it is compared with', async () => {
    const review = weekReviewFixture();
    review.window = { ...review.window, is_complete: false, counted_days: 3, compared_days: 3 };
    await ready(review);

    const note = screen.getByRole('status');
    expect(note.textContent).toContain('Неделя не закончилась');
    expect(note.textContent).toContain('первыми 3 днями');
  });

  it('shows no unfinished-week note on a finished week', async () => {
    await ready(weekReviewFixture());

    expect(screen.queryByText('Неделя не закончилась', { exact: false })).toBeNull();
  });

  it('links to the neighbour weeks and to the retro', async () => {
    await ready(weekReviewFixture());

    expect(screen.getByText('← 2026-W34').closest('a')?.getAttribute('href')).toBe(
      '/week/review/2026-W34'
    );
    expect(screen.getByText('2026-W36 →').closest('a')?.getAttribute('href')).toBe(
      '/week/review/2026-W36'
    );
    expect(screen.getByText('Ретро недели').closest('a')?.getAttribute('href')).toBe(
      '/week/2026-W35'
    );
  });

  it('keeps the mobile reader inside /m on every link of the screen', async () => {
    await ready(weekReviewFixture(), true);

    expect(screen.getByText('← 2026-W34').closest('a')?.getAttribute('href')).toBe(
      '/m/week/review/2026-W34'
    );
    expect(screen.getByText('2026-W36 →').closest('a')?.getAttribute('href')).toBe(
      '/m/week/review/2026-W36'
    );
    expect(screen.getByText('Ретро недели').closest('a')?.getAttribute('href')).toBe(
      '/m/week/2026-W35'
    );
  });

  it('prints the verdict line exactly as the server wrote it, with no second copy', async () => {
    const review = weekReviewFixture();
    review.verdict_line = 'Неделя выиграна: да (строка сервера, не копия экрана).';
    await ready(review);

    expect(screen.getByText('Неделя выиграна: да (строка сервера, не копия экрана).')).toBeDefined();
    expect(screen.queryByText('выиграно 2 из 3 дней', { exact: false })).toBeNull();
  });

  it('explains on a running week why the role shares may differ from the retro', async () => {
    const review = weekReviewFixture();
    review.window = { ...review.window, is_complete: false, counted_days: 3, compared_days: 3 };
    review.is_won = null;
    await ready(review);

    expect(screen.getByText(ROLES_RUNNING_WEEK_NOTE)).toBeDefined();
  });

  it('drops the role note on a running week once today is counted', async () => {
    const review = weekReviewFixture();
    review.window = {
      ...review.window,
      is_complete: false,
      counted_days: 3,
      compared_days: 3,
      today_counted: true,
    };
    review.is_won = null;
    await ready(review);

    expect(screen.queryByText(ROLES_RUNNING_WEEK_NOTE)).toBeNull();
  });

  it('adds no role note on a finished week', async () => {
    await ready(weekReviewFixture());

    expect(screen.queryByText(ROLES_RUNNING_WEEK_NOTE)).toBeNull();
  });

  it('keeps the narrative block a polite live region', async () => {
    await ready(weekReviewFixture());

    expect(screen.getByLabelText('Итог от ИИ').getAttribute('aria-live')).toBe('polite');
  });

  it('renders on the mobile type scale without changing the numbers', async () => {
    await ready(weekReviewFixture(), true);

    expect(screen.getByRole('heading', { level: 1 }).className).toContain('text-2xl');
    expect(screen.getByText('67%')).toBeDefined();
  });

  it('says an empty week is empty and does not offer the narrative', async () => {
    const review = weekReviewFixture();
    review.totals = { ...review.totals, closed_days: 0, tasks_total: 0, role_minutes: 0 };
    review.categories = [];
    review.habit_streaks = [];
    review.health = review.health.map((metric) => ({ ...metric, days_with_data: 0 }));
    render(<WeekReviewScreen iso="2026-W35" client={clientOf(review)} />);

    await waitFor(() => expect(screen.getByText('За эту неделю данных пока нет.')).toBeDefined());
    const button = screen.getByRole('button', { name: NARRATIVE_BUTTON });
    expect(button.hasAttribute('disabled')).toBe(true);
  });

  it('writes the narrative only when asked, and shows what the model said', async () => {
    const client = await ready(weekReviewFixture());
    expect(client.narrate).toHaveBeenCalledTimes(0);

    fireEvent.click(screen.getByRole('button', { name: NARRATIVE_BUTTON }));

    await waitFor(() => expect(screen.getByText('Неделя прошла ровно.')).toBeDefined());
    expect(client.narrate).toHaveBeenCalledTimes(1);
  });

  it('shows the refusal in its own words when the model backend is off', async () => {
    const review = weekReviewFixture();
    const client = clientOf(review, () => Promise.reject({ status: 503 }));
    render(<WeekReviewScreen iso="2026-W35" client={client} />);
    await waitFor(() => expect(screen.getByText('Итог недели')).toBeDefined());

    fireEvent.click(screen.getByRole('button', { name: NARRATIVE_BUTTON }));

    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('Итог от ИИ выключен')
    );
  });

  it('shows the load error and lets it be dismissed to retry', async () => {
    const get = mock(() => Promise.reject(new Error('Сеть недоступна')));
    render(
      <WeekReviewScreen
        iso="2026-W35"
        client={{ get, narrative: () => Promise.reject(new Error('x')) }}
      />
    );

    await waitFor(() => expect(screen.getByText('Сеть недоступна')).toBeDefined());
    fireEvent.click(screen.getByLabelText('Dismiss error'));

    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });

  it('keeps the advice block with its disclaimer on a week without supplements, and no supplements block', async () => {
    await ready(weekReviewFixture());

    expect(screen.getByText('Это не медицинская рекомендация.')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Написать совет' })).toBeDefined();
    expect(screen.queryByText('Добавки')).toBeNull();
  });

  it('shows taken of planned supplements when the week has them', async () => {
    const review = weekReviewFixture();
    review.supplements = adherenceFixture();
    await ready(review);

    expect(screen.getByText('Добавки')).toBeDefined();
    expect(screen.getByText('3 из 7')).toBeDefined();
    expect(screen.getByText('Магний цитрат')).toBeDefined();
  });

  it('writes the advice only on the tap', async () => {
    const write = mock(() =>
      Promise.resolve({
        text: 'Ходи больше.',
        model: 'm',
        starts_on: '2026-10-24',
        ends_on: '2026-10-30',
        days: 7,
      })
    );
    render(
      <WeekReviewScreen
        iso="2026-W35"
        client={clientOf(weekReviewFixture())}
        adviceClient={{ write }}
      />
    );
    await waitFor(() => expect(screen.getByText('Итог недели')).toBeDefined());
    expect(write).toHaveBeenCalledTimes(0);

    fireEvent.click(screen.getByRole('button', { name: 'Написать совет' }));

    await waitFor(() => expect(screen.getByText('Ходи больше.')).toBeDefined());
    expect(write).toHaveBeenCalledTimes(1);
  });
});
