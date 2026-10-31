// [review:need-review] #302
// summary: tests for each dashboard block - rings (full, too little health data, nothing), streaks with dots and the five-row fold, health against the norm, bests with the record mark, workout bars, the insight and the nutrition placeholder - and for the empty answer of each, which is a line of words and never a zero

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { emptySummary, fullSummary } from '@/test-fixtures/dashboard-summary';
import type { DashboardStreak } from '@/lib/api';
import { BestsBlock } from './BestsBlock';
import { HealthNormBlock } from './HealthNormBlock';
import { InsightBlock } from './InsightBlock';
import { NutritionSoonBlock } from './NutritionSoonBlock';
import { ScoreRings } from './ScoreRings';
import { STREAKS_COLLAPSED, StreaksBlock } from './StreaksBlock';
import { WorkoutsBlock } from './WorkoutsBlock';

afterEach(() => {
  cleanup();
});

describe('ScoreRings', () => {
  it('shows the three scores with their numbers', () => {
    render(<ScoreRings scores={fullSummary().scores} />);

    const rings = screen.getByRole('region', { name: 'Общий показатель' });
    expect(within(rings).getAllByRole('listitem')).toHaveLength(3);
    expect(within(rings).getByText('78')).toBeTruthy();
    expect(within(rings).getByText('Хорошо · за 7 дней')).toBeTruthy();
    expect(within(rings).getByText('64%')).toBeTruthy();
    expect(within(rings).getByText('45 из 70 отметок')).toBeTruthy();
    expect(within(rings).getByText('3/5')).toBeTruthy();
  });

  it('says how many days are missing instead of drawing a health zero', () => {
    render(<ScoreRings scores={emptySummary().scores} />);

    expect(screen.getByText('Мало данных: 1 из 3 дн.')).toBeTruthy();
    expect(screen.queryByText('0')).toBeNull();
    expect(screen.getAllByText('—')).toHaveLength(3);
  });

  it('names a missing plan and missing challenges', () => {
    render(
      <ScoreRings
        scores={{
          health: null,
          habits: { value: null, done: 0, total: 0 },
          challenges: { done: 0, total: 0 },
        }}
      />
    );

    expect(screen.getByText('Нет данных')).toBeTruthy();
    expect(screen.getByText('План не задан')).toBeTruthy();
    expect(screen.getByText('Челленджей нет')).toBeTruthy();
  });
});

describe('StreaksBlock', () => {
  it('lists current and best length and describes the day dots in words', () => {
    render(<StreaksBlock streaks={fullSummary().streaks} />);

    const block = screen.getByRole('region', { name: 'Серии' });
    const cold = within(block).getByRole('link', { name: /Холодный душ/ });
    expect(cold.getAttribute('href')).toBe('/categories/1');
    expect(within(cold).getByText('12 дней')).toBeTruthy();
    expect(within(cold).getByText('лучшая серия 21 день')).toBeTruthy();
    expect(
      within(cold).getByRole('img', {
        name: 'Последние 7 дней: выполнено 6, пропущено 1, нет данных 0',
      })
    ).toBeTruthy();
  });

  it('speaks of relapses for an avoid category and links to the mobile page in the mobile shell', () => {
    render(<StreaksBlock streaks={fullSummary().streaks} mobile />);

    const sugar = screen.getByRole('link', { name: /Без сахара/ });
    expect(sugar.getAttribute('href')).toBe('/m/categories/2');
    expect(within(sugar).getByRole('img').getAttribute('aria-label')).toContain('без срыва');
    expect(within(sugar).getByRole('img').getAttribute('aria-label')).toContain('срывов');
  });

  it('folds after five rows and opens the rest on request', () => {
    const many: DashboardStreak[] = Array.from({ length: STREAKS_COLLAPSED + 2 }, (_, index) => ({
      category_id: index + 1,
      name: `Привычка ${index + 1}`,
      kind: 'build',
      current: index,
      best: index + 3,
      days: [true, false, null],
    }));
    render(<StreaksBlock streaks={many} />);

    expect(screen.getAllByRole('link')).toHaveLength(STREAKS_COLLAPSED);
    const more = screen.getByRole('button', { name: 'Показать все (ещё 2)' });
    expect(more.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(more);
    expect(screen.getAllByRole('link')).toHaveLength(STREAKS_COLLAPSED + 2);
    expect(screen.getByRole('button', { name: 'Свернуть' }).getAttribute('aria-expanded')).toBe(
      'true'
    );
  });

  it('has no fold button for a short list', () => {
    render(<StreaksBlock streaks={fullSummary().streaks} />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('is a line of words when there are no streaks', () => {
    render(<StreaksBlock streaks={[]} />);
    expect(screen.getByText(/Серий пока нет: данных мало/)).toBeTruthy();
  });
});

describe('HealthNormBlock', () => {
  it('shows sleep and resting pulse with the distance from the personal norm', () => {
    render(<HealthNormBlock metrics={fullSummary().health} />);

    expect(screen.getByText('7 ч 12 мин')).toBeTruthy();
    expect(screen.getByText('+20 мин от вашей нормы')).toBeTruthy();
    expect(screen.getByText('58 уд/мин')).toBeTruthy();
    expect(screen.getByText('−2 уд/мин от вашей нормы')).toBeTruthy();
  });

  it('colours a lower resting pulse as better and shorter sleep as worse', () => {
    render(
      <HealthNormBlock
        metrics={[
          { identifier: 'sleep_duration', label: 'Сон', value: 400, unit: 'min', baseline_delta: -30 },
          {
            identifier: 'resting_heart_rate',
            label: 'Пульс покоя',
            value: 56,
            unit: 'count/min',
            baseline_delta: -3,
          },
        ]}
      />
    );

    expect(screen.getByText('−30 мин от вашей нормы').className).toContain('text-danger');
    expect(screen.getByText('−3 уд/мин от вашей нормы').className).toContain('text-success');
  });

  it('says the norm is not known yet and does not invent a value', () => {
    render(
      <HealthNormBlock
        metrics={[
          { identifier: 'sleep_duration', label: 'Сон', value: null, unit: 'min', baseline_delta: null },
        ]}
      />
    );

    expect(screen.getByText('—')).toBeTruthy();
    expect(screen.getByText('нормы пока нет')).toBeTruthy();
  });

  it('is a line of words when nothing came from Health', () => {
    render(<HealthNormBlock metrics={[]} />);
    expect(screen.getByText(/Данных мало: сон и пульс/)).toBeTruthy();
  });
});

describe('BestsBlock', () => {
  it('shows the value, the day and the record mark', () => {
    render(<BestsBlock bests={fullSummary('month').bests} period="month" />);

    const block = screen.getByRole('region', { name: 'Лучшее за месяц' });
    expect(within(block).getByText(/^14\s220$/)).toBeTruthy();
    expect(within(block).getByText('28 окт')).toBeTruthy();
    expect(within(block).getAllByText('Рекорд')).toHaveLength(1);
  });

  it('names the week when the window is a week', () => {
    render(<BestsBlock bests={[]} period="week" />);
    expect(screen.getByRole('region', { name: 'Лучшее за неделю' })).toBeTruthy();
    expect(screen.getByText(/Данных мало/)).toBeTruthy();
  });
});

describe('WorkoutsBlock', () => {
  it('draws a bar per week and reads each aloud with its count and minutes', () => {
    render(<WorkoutsBlock workouts={fullSummary().workouts} />);

    const weeks = screen.getByRole('list', { name: 'Тренировки по неделям' });
    expect(within(weeks).getAllByRole('listitem')).toHaveLength(3);
    expect(within(weeks).getByText('Неделя с 12 окт: 4 тренировки, 3 ч 20 мин')).toBeTruthy();
    expect(screen.getByText(/всего 9/)).toBeTruthy();
    expect(screen.getByText('+1 к прошлому периоду')).toBeTruthy();
  });

  it('leaves out the comparison when the server has none', () => {
    const workouts = fullSummary().workouts;
    render(
      <WorkoutsBlock workouts={workouts === null ? null : { ...workouts, delta_vs_previous: null }} />
    );
    expect(screen.queryByText(/к прошлому периоду/)).toBeNull();
  });

  it('is a line of words without workouts', () => {
    render(<WorkoutsBlock workouts={null} />);
    expect(screen.getByText(/тренировок в этом окне не записано/)).toBeTruthy();
  });
});

describe('InsightBlock', () => {
  it('shows the text, the server time it was made and the way to the history', () => {
    render(<InsightBlock insight={fullSummary().insight} />);

    expect(screen.getByRole('region', { name: 'Инсайт недели' })).toBeTruthy();
    expect(screen.getByText(/Сон дольше 7 часов/)).toBeTruthy();
    expect(screen.getByText('Сформирован 31 окт, 09:00')).toBeTruthy();
    expect(screen.getByRole('link', { name: /История разборов/ }).getAttribute('href')).toBe(
      '/insights'
    );
  });

  it('links to the mobile history in the mobile shell', () => {
    render(<InsightBlock insight={fullSummary().insight} mobile />);
    expect(screen.getByRole('link', { name: /История разборов/ }).getAttribute('href')).toBe(
      '/m/insights'
    );
  });

  it('is a line of words without an insight', () => {
    render(<InsightBlock insight={null} />);
    expect(screen.getByText(/инсайт появится/)).toBeTruthy();
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('NutritionSoonBlock', () => {
  it('holds the place and offers nothing to press', () => {
    render(<NutritionSoonBlock />);

    expect(screen.getByRole('region', { name: 'Питание · скоро' })).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });
});
