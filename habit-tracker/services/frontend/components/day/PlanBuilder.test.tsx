// [review:need-review] PHASE-03/147, PHASE-03/148
// summary: tests for the card that builds a day's plan — the button calls generation with this day's date, the wait is said out loud while the model thinks, a second click writes no second plan, a refusal is shown in words and only then offers the canon-only skeleton, and a plan that got built hands the day back to be re-read

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Plan } from '@/lib/api';

/** What both endpoints answer with. The hook re-reads the day and ignores it. */
const PLAN: Plan = {
  id: 'p1',
  day_date: '2026-08-30',
  title: 'План 2026-08-30 (вс)',
  title_marker: null,
  lede: null,
  purpose_md: null,
  quarter_goal_id: null,
  counters: [],
  condition_tomorrow: null,
  status: 'active',
  source: 'llm',
  fallback_reason: null,
  needs_review: false,
  created_at: '2026-08-30T06:00:00Z',
  updated_at: '2026-08-30T06:00:00Z',
  sections: [],
  schedule: [],
  overlaps: [],
};

let generated: string[] = [];
let skeletons: string[] = [];
let generationFails: Error | null = null;
let holdGeneration = false;
let releaseGeneration: (() => void) | null = null;

// Подменяется только `dayAPI`, остальной модуль остаётся настоящим: реестр
// модулей у bun общий на прогон, и подмена всего `@/lib/api` уронила бы файлы,
// которые читают из него что-то ещё.
const actual = await import('@/lib/api');
mock.module('@/lib/api', () => ({
  ...actual,
  dayAPI: {
    ...actual.dayAPI,
    generatePlan: async (date: string) => {
      generated.push(date);
      if (holdGeneration) {
        await new Promise<void>((resolve) => {
          releaseGeneration = resolve;
        });
      }
      if (generationFails !== null) throw generationFails;
      return PLAN;
    },
    buildSkeleton: async (date: string) => {
      skeletons.push(date);
      return PLAN;
    },
  },
}));

const {
  default: PlanBuilder,
  BUILD_FALLBACK_HINT,
  BUILD_PLAN_LABEL,
  BUILD_PLAN_RETRY_LABEL,
  BUILD_PLAN_RUNNING,
  BUILD_SKELETON_LABEL,
} = await import('./PlanBuilder');

afterEach(() => {
  cleanup();
  generated = [];
  skeletons = [];
  generationFails = null;
  holdGeneration = false;
  releaseGeneration = null;
});

describe('PlanBuilder', () => {
  it('просит модель собрать план именно на этот день', async () => {
    // Кнопка, которая не доходит до ручки, — это прежний тупик с картинкой.
    render(<PlanBuilder date="2026-08-30" onBuilt={() => {}} />);

    fireEvent.click(screen.getByText(BUILD_PLAN_LABEL));

    await waitFor(() => expect(generated).toEqual(['2026-08-30']));
  });

  it('пока модель думает, ожидание видно', async () => {
    // Генерация занимает секунды: без этой строки человек не знает, нажалось
    // ли, и жмёт второй раз.
    holdGeneration = true;
    render(<PlanBuilder date="2026-08-30" onBuilt={() => {}} />);

    const button = screen.getByText(BUILD_PLAN_LABEL);
    fireEvent.click(button);

    expect(screen.getByText(BUILD_PLAN_RUNNING)).toBeDefined();
    expect((button as HTMLButtonElement).disabled).toBe(true);

    releaseGeneration?.();
    await waitFor(() => expect(screen.queryByText(BUILD_PLAN_RUNNING)).toBeNull());
  });

  it('второй клик не пишет второй план', async () => {
    // Ответ ручки — это `replace_plan`: два запроса подряд затирают друг друга.
    holdGeneration = true;
    render(<PlanBuilder date="2026-08-30" onBuilt={() => {}} />);

    const button = screen.getByText(BUILD_PLAN_LABEL);
    fireEvent.click(button);
    fireEvent.click(button);

    expect(generated).toEqual(['2026-08-30']);
    releaseGeneration?.();
    await waitFor(() => expect(screen.queryByText(BUILD_PLAN_RUNNING)).toBeNull());
  });

  it('отказ объясняется словами, а не кодом', async () => {
    generationFails = new Error('модель не настроена');
    render(<PlanBuilder date="2026-08-30" onBuilt={() => {}} />);

    fireEvent.click(screen.getByText(BUILD_PLAN_LABEL));

    await waitFor(() => expect(screen.getByText('модель не настроена')).toBeDefined());
    expect(screen.getByText(BUILD_PLAN_RETRY_LABEL)).toBeDefined();
  });

  it('скелет предлагается только после отказа', () => {
    // Две равные кнопки утром означали бы выбор руками каждый день, и день
    // перестал бы планироваться моделью вовсе.
    render(<PlanBuilder date="2026-08-30" onBuilt={() => {}} />);

    expect(screen.queryByText(BUILD_SKELETON_LABEL)).toBeNull();
    expect(screen.queryByText(BUILD_FALLBACK_HINT)).toBeNull();
  });

  it('после отказа скелет собирается без модели', async () => {
    generationFails = new Error('модель не ответила');
    render(<PlanBuilder date="2026-08-30" onBuilt={() => {}} />);
    fireEvent.click(screen.getByText(BUILD_PLAN_LABEL));
    await waitFor(() => expect(screen.getByText(BUILD_SKELETON_LABEL)).toBeDefined());

    expect(screen.getByText(BUILD_FALLBACK_HINT)).toBeDefined();
    fireEvent.click(screen.getByText(BUILD_SKELETON_LABEL));

    await waitFor(() => expect(skeletons).toEqual(['2026-08-30']));
  });

  it('собранный план возвращает день на перечитывание', async () => {
    // Экран не склеивает ответ руками: сервер перенумеровал секции, посчитал
    // расписание и записал нарушения — угадать это здесь нечем.
    let reloaded = 0;
    render(<PlanBuilder date="2026-08-30" onBuilt={() => { reloaded += 1; }} />);

    fireEvent.click(screen.getByText(BUILD_PLAN_LABEL));

    await waitFor(() => expect(reloaded).toBe(1));
  });
});
