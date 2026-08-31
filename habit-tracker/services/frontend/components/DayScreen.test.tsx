// [review:need-review] PHASE-03/86, PHASE-03/87, PHASE-03/88, PHASE-03/90, PHASE-03/94
// summary: tests for the day screen — a day with no plan says so and offers the button that builds one instead of rendering a dead end, the button is gone the moment there is a plan, a plan the skeleton assembled says so and says why, the rules a plan broke are visible beside it, the rule the day is judged by is on the screen, a day nobody opened says so, and the notebook and the итог of the day are there

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { DayDetail, PlanViolation } from '@/lib/api';
import { DAY, PLAN } from '@/test-fixtures/day';
import { NOTEBOOK_TITLE } from '@/components/day/DayNotebook';
import { NO_PLAN_TEXT } from '@/lib/day-format';
import { DAY_NEVER_OPENED } from '@/lib/marks';
import { BUILD_PLAN_LABEL } from '@/components/day/PlanBuilder';
import {
  FALLBACK_REASON_LABELS,
  NEEDS_REVIEW_BADGE,
  planAuthorLabel,
  ruleLabel,
} from '@/lib/plan-violations';

let state: {
  detail: DayDetail | null;
  loading: boolean;
  error: string | null;
  violations: PlanViolation[];
  reload: () => void;
};

// The hook rather than the API client: the screen's contract is the hook, and
// mocking one export keeps this suite out of the shared `@/lib/api` registry.
mock.module('@/hooks/useDay', () => ({
  useDay: () => state,
}));

// The screen carries the shared day navigation since `#94`; it fetches a range
// of its own, and this test is about the day rather than about the list beside it.
mock.module('@/hooks/useDays', () => ({
  useDays: () => ({ days: [], loading: false, error: null, reload: () => {} }),
  LOAD_DAYS_ERROR: 'Не удалось загрузить дни',
}));

const { default: DayScreen } = await import('./DayScreen');

beforeEach(() => {
  state = { detail: DAY, loading: false, error: null, violations: [], reload: () => {} };
});

afterEach(() => {
  cleanup();
});

describe('DayScreen', () => {
  it('says "плана нет" on a day without a plan', () => {
    // The whole reason the endpoint answers instead of 404ing: an empty day is
    // an answer, and a blank screen would read as a broken one.
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText(NO_PLAN_TEXT)).toBeDefined();
  });

  it('shows the date and what kind of day it is', () => {
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText('2026-08-30')).toBeDefined();
    expect(screen.getByText('выходной')).toBeDefined();
  });

  it('explains which rule this day is counted by', () => {
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText('действует с 2026-08-17')).toBeDefined();
    expect(screen.getByText('8 ч в день')).toBeDefined();
  });

  it('marks a no-code day', () => {
    state = { ...state, detail: { ...DAY, day: { ...DAY.day, is_nocode: true } } };
    render(<DayScreen date="2026-09-01" />);

    expect(screen.getByText('no-code day')).toBeDefined();
  });

  it('renders the plan instead of the "плана нет" block once there is one', () => {
    state = { ...state, detail: { ...DAY, plan: PLAN, has_plan: true } };
    render(<DayScreen date="2026-08-30" />);

    expect(screen.queryByText(NO_PLAN_TEXT)).toBeNull();
    expect(screen.getByText('Воскресный блок')).toBeDefined();
    expect(screen.getByText('Расписание дня')).toBeDefined();
  });

  it('says how many work tasks the plan spends of the bar', () => {
    // The bar is the rule's, not a constant: a day under the legacy canon is
    // read against different numbers, and the screen has to show which.
    state = { ...state, detail: { ...DAY, plan: PLAN, has_plan: true } };
    render(<DayScreen date="2026-08-30" />);

    expect(
      screen.getByText(/Рабочих задач: 0 из 4 · закрыто 0 из 0/)
    ).toBeDefined();
  });

  it('says outright when nobody has opened the day', () => {
    // One of the four kinds of empty `#88` separates: a day with no marks that
    // nobody ever came to is not a day where nothing was done.
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText(DAY_NEVER_OPENED)).toBeDefined();
  });

  it('keeps that badge off a day that was opened', () => {
    state = {
      ...state,
      detail: { ...DAY, day: { ...DAY.day, opened_at: '2026-08-30T07:10:00Z' } },
    };
    render(<DayScreen date="2026-08-30" />);

    expect(screen.queryByText(DAY_NEVER_OPENED)).toBeNull();
  });

  it('offers the notebook of the day', () => {
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByLabelText(NOTEBOOK_TITLE)).toBeDefined();
  });

  it('shows the failure instead of an empty day', () => {
    state = { detail: null, loading: false, error: 'нет правила', violations: [], reload: () => {} };
    render(<DayScreen date="1999-01-01" />);

    expect(screen.getByText('нет правила')).toBeDefined();
  });
});

describe('DayScreen and the plan built overnight', () => {
  it('says the plan was built overnight and nobody looked at it', () => {
    // Ночной прогон строит только скелет; человек утром должен видеть это, а
    // не думать, что план кто-то продумал.
    state = {
      detail: { ...DAY, plan: { ...PLAN, needs_review: true } },
      loading: false,
      error: null,
      violations: [],
      reload: () => {},
    };
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText(NEEDS_REVIEW_BADGE)).toBeDefined();
  });

  it('says nothing of the kind about a plan somebody made', () => {
    render(<DayScreen date="2026-08-30" />);

    expect(screen.queryByText(NEEDS_REVIEW_BADGE)).toBeNull();
  });
});

describe('DayScreen и день без плана', () => {
  it('предлагает собрать план, а не оставляет тупик', () => {
    // Ради чего слайс: обе ручки сборки лежали на сервере неделями, а экран
    // говорил «плана нет» и не давал ничего сделать.
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText(BUILD_PLAN_LABEL)).toBeDefined();
  });

  it('убирает кнопку, как только план есть', () => {
    // Кнопка на дне с планом означала бы «собрать заново поверх» — а это
    // перезапись того, что человек уже правил и отмечал.
    state = { ...state, detail: { ...DAY, plan: PLAN, has_plan: true } };
    render(<DayScreen date="2026-08-30" />);

    expect(screen.queryByText(BUILD_PLAN_LABEL)).toBeNull();
  });

  it('после сборки план на экране, а кнопки нет', () => {
    // Сборка перечитывает день, и это единственное, что меняется на экране:
    // ответ сервера — новая истина, склеивать его руками нечем.
    const { rerender } = render(<DayScreen date="2026-08-30" />);
    expect(screen.getByText(BUILD_PLAN_LABEL)).toBeDefined();

    state = { ...state, detail: { ...DAY, plan: PLAN, has_plan: true } };
    rerender(<DayScreen date="2026-08-30" />);

    expect(screen.getByText('Воскресный блок')).toBeDefined();
    expect(screen.queryByText(BUILD_PLAN_LABEL)).toBeNull();
  });

  it('называет скелет скелетом и говорит, почему не модель', () => {
    // «Собрался скелет» — это состояние дня, а не примечание: план без задач
    // модели человек обязан узнать с экрана, а не по пустому расписанию.
    const skeleton = {
      ...PLAN,
      source: 'fallback' as const,
      fallback_reason: 'llm_not_configured' as const,
    };
    state = { ...state, detail: { ...DAY, plan: skeleton, has_plan: true } };
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText(planAuthorLabel(skeleton))).toBeDefined();
    expect(
      screen.getByText(`Почему: ${FALLBACK_REASON_LABELS.llm_not_configured}`)
    ).toBeDefined();
  });

  it('показывает правила, которые нарушил собранный план', () => {
    // Нарушения приезжают тем же перечитыванием дня, что и сам план: у
    // собранного плана они обязаны появиться, а не остаться от прошлого.
    state = {
      ...state,
      detail: { ...DAY, plan: PLAN, has_plan: true },
      violations: [
        {
          id: 1,
          day_date: '2026-08-30',
          rule_code: 'free_evening_empty' as const,
          severity: 'warn' as const,
          origin: 'ai' as const,
          detail: {},
          created_at: '2026-08-30T06:00:00Z',
        },
      ],
    };
    render(<DayScreen date="2026-08-30" />);

    expect(screen.getByText(ruleLabel('free_evening_empty'))).toBeDefined();
  });
});
