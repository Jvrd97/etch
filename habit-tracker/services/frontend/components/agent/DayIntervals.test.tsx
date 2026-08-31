// [review:need-review] PHASE-03/160
// summary: component tests of «где прошёл день» — overlapping intervals do not double the total on screen, a corrected interval is visually distinct, a dropped title reads «скрыт правилом» with a link to the rules rather than as an empty cell, the untasked row appears only when there is work outside a task, and the pencil opens the editor whose save carries only what changed

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ActivityDay, ActivityInterval } from '@/lib/api';
import {
  CORRECTED_MARK,
  EMPTY_ACTIVITY_TEXT,
  TITLE_HIDDEN_TEXT,
  TITLE_RULES_LINK_TEXT,
  UNTASKED_LABEL,
} from '@/lib/interval-rollup';

const patched = mock((_id: number, _patch: unknown) => Promise.resolve());

function interval(overrides: Partial<ActivityInterval> = {}): ActivityInterval {
  return {
    id: 1,
    source: 'agent',
    app_id: 2,
    bundle_id: 'com.microsoft.VSCode',
    app_name: 'VS Code',
    plan_task_id: null,
    clickup_task_id: null,
    corrected_at: null,
    started_at: '2026-08-31T08:00:00.000Z',
    ended_at: '2026-08-31T10:00:00.000Z',
    duration_seconds: 7200,
    local_date: '2026-08-31',
    title_source: 'masked',
    idle_seconds: 0,
    switch_count: 0,
    is_corrected: false,
    note: null,
    ...overrides,
  };
}

function withDay(day: ActivityDay | null) {
  mock.module('@/hooks/useDayActivity', () => ({
    LOAD_ACTIVITY_ERROR: 'Не удалось загрузить активность дня',
    useDayActivity: () => ({
      day,
      loading: false,
      saving: false,
      error: null,
      patch: patched,
      addManual: () => Promise.resolve(),
    }),
  }));
}

function day(overrides: Partial<ActivityDay> = {}): ActivityDay {
  return {
    work_day: '2026-08-31',
    mode: 'work',
    total_minutes: 120,
    apps: [
      { app_id: 2, bundle_id: 'com.microsoft.VSCode', app_name: 'VS Code', minutes: 120 },
    ],
    tasks: [{ plan_task_id: 42, clickup_task_id: null, minutes: 120 }],
    untasked_minutes: 0,
    intervals: [interval({ plan_task_id: 42 })],
    ...overrides,
  };
}

async function draw(body: ActivityDay | null) {
  withDay(body);
  const { default: DayIntervals } = await import('./DayIntervals');
  render(<DayIntervals date="2026-08-31" />);
}

afterEach(() => {
  cleanup();
  patched.mockClear();
});

describe('где прошёл день', () => {
  it('показывает по задаче число сервера, а не сумму строк ленты', async () => {
    // Две пересекающиеся записи по два часа: сумма — четыре, объединение — два.
    await draw(
      day({
        total_minutes: 240,
        tasks: [{ plan_task_id: 42, clickup_task_id: null, minutes: 120 }],
        intervals: [
          interval({ id: 1, plan_task_id: 42 }),
          interval({
            id: 2,
            source: 'manual',
            app_id: null,
            app_name: null,
            bundle_id: null,
            plan_task_id: 42,
            started_at: '2026-08-31T08:30:00.000Z',
            ended_at: '2026-08-31T10:30:00.000Z',
          }),
        ],
      })
    );
    expect(screen.getByText('задача 42')).toBeTruthy();
    // Два часа под задачей, при четырёх часах строк в ленте.
    expect(screen.getAllByText('2 ч').length).toBeGreaterThan(0);
    expect(screen.queryByText('4 ч')).toBeNull();
  });

  it('исправленный интервал отличим от нетронутого', async () => {
    await draw(
      day({
        intervals: [
          interval({ id: 1 }),
          interval({ id: 2, is_corrected: true, corrected_at: '2026-08-31T12:00:00Z' }),
        ],
      })
    );
    expect(screen.getAllByText(CORRECTED_MARK).length).toBe(1);
  });

  it('скрытый заголовок подписан правилом и ведёт на экран правил', async () => {
    await draw(day({ intervals: [interval({ title_source: 'dropped' })] }));
    expect(screen.getByText(new RegExp(TITLE_HIDDEN_TEXT))).toBeTruthy();
    const link = screen.getByText(TITLE_RULES_LINK_TEXT) as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('/agent/title-rules');
  });

  it('строка «без задачи» появляется только когда такие интервалы есть', async () => {
    await draw(day());
    expect(screen.queryByText(UNTASKED_LABEL)).toBeNull();
    cleanup();

    await draw(day({ untasked_minutes: 90 }));
    expect(screen.getByText(UNTASKED_LABEL)).toBeTruthy();
  });

  it('день без активности говорит об этом словами', async () => {
    await draw(day({ intervals: [], apps: [], tasks: [], total_minutes: 0 }));
    expect(screen.getByText(EMPTY_ACTIVITY_TEXT)).toBeTruthy();
  });

  it('карандаш открывает редактор, и он везёт только изменённое', async () => {
    await draw(day());
    fireEvent.click(screen.getByLabelText(/Править интервал/));
    const end = screen.getByLabelText('Конец интервала');
    fireEvent.change(end, { target: { value: '11:30' } });
    fireEvent.click(screen.getByText('Сохранить'));

    expect(patched).toHaveBeenCalled();
    const [id, patch] = patched.mock.calls[0] as [number, Record<string, unknown>];
    expect(id).toBe(1);
    expect(Object.keys(patch)).toEqual(['ended_at']);
  });
});
