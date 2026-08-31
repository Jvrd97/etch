// [review:need-review] PHASE-03/160
// summary: pure tests of the day's readings — the task total is the server's union rather than a sum of the drawn rows, a manual record is named as typed rather than by an application, a dropped title reads «скрыт правилом», the untasked row appears only when there is work outside a task, and one end of an interval is moved without moving its date

import { describe, expect, it } from 'bun:test';
import type { ActivityDay, ActivityInterval } from '@/lib/api';
import {
  MANUAL_SOURCE_TEXT,
  UNTASKED_LABEL,
  hasUntasked,
  intervalSource,
  taskLabel,
  taskTotalMinutes,
  titleIsHidden,
} from '@/lib/interval-rollup';
import { changedFields, clockField, withClock } from '@/components/agent/IntervalEditor';

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
    title_source: 'dropped',
    idle_seconds: 0,
    switch_count: 0,
    is_corrected: false,
    note: null,
    ...overrides,
  };
}

function day(overrides: Partial<ActivityDay> = {}): ActivityDay {
  return {
    work_day: '2026-08-31',
    mode: 'work',
    total_minutes: 180,
    apps: [
      { app_id: 2, bundle_id: 'com.microsoft.VSCode', app_name: 'VS Code', minutes: 180 },
    ],
    tasks: [{ plan_task_id: 42, clickup_task_id: null, minutes: 120 }],
    untasked_minutes: 0,
    intervals: [interval()],
    ...overrides,
  };
}

describe('свёртка по задачам', () => {
  it('берётся у сервера, а не складывается из строк ленты', () => {
    // Две пересекающиеся записи по 2 ч: сумма длительностей — 4 ч, объединение —
    // 2 ч. Экран обязан показать то, что посчитал сервер.
    const overlapping = day({
      tasks: [{ plan_task_id: 42, clickup_task_id: null, minutes: 120 }],
      intervals: [
        interval({ id: 1, plan_task_id: 42 }),
        interval({
          id: 2,
          source: 'manual',
          app_id: null,
          bundle_id: null,
          app_name: null,
          plan_task_id: 42,
          started_at: '2026-08-31T08:30:00.000Z',
          ended_at: '2026-08-31T10:30:00.000Z',
        }),
      ],
    });
    const summed = overlapping.intervals.reduce(
      (total, row) => total + row.duration_seconds / 60,
      0
    );
    expect(summed).toBe(240);
    expect(taskTotalMinutes(overlapping)).toBe(120);
  });

  it('называет задачу так же, как её называют везде', () => {
    expect(taskLabel(42, null)).toBe('задача 42');
    expect(taskLabel(null, 'CU-123')).toBe('CU-123');
    expect(taskLabel(null, null)).toBe(UNTASKED_LABEL);
  });
});

describe('строка «без задачи»', () => {
  it('появляется, когда работа вне плана была', () => {
    expect(hasUntasked(day({ untasked_minutes: 90 }))).toBe(true);
  });

  it('молчит, когда всё привязано', () => {
    expect(hasUntasked(day())).toBe(false);
  });
});

describe('строка ленты', () => {
  it('ручная запись названа записанной руками, а не приложением', () => {
    expect(
      intervalSource(
        interval({ source: 'manual', app_id: null, app_name: null, bundle_id: null })
      )
    ).toBe(MANUAL_SOURCE_TEXT);
  });

  it('авто-интервал назван приложением', () => {
    expect(intervalSource(interval())).toBe('VS Code');
  });

  it('скрытый заголовок отличается от отсутствующего', () => {
    expect(titleIsHidden(interval({ title_source: 'dropped' }))).toBe(true);
    expect(titleIsHidden(interval({ title_source: 'masked' }))).toBe(false);
  });
});

describe('правка интервала', () => {
  it('везёт только то, что человек поменял', () => {
    const row = interval();
    const patch = changedFields(row, {
      from: clockField(row.started_at),
      to: '11:30',
      task: '42',
      note: '',
    });
    expect(patch.started_at).toBeUndefined();
    expect(patch.ended_at).toBeTruthy();
    expect(patch.plan_task_id).toBe(42);
    expect(patch.note).toBeUndefined();
  });

  it('пустая задача — это «убрать привязку», а не «не трогать»', () => {
    const row = interval({ plan_task_id: 42 });
    const patch = changedFields(row, {
      from: clockField(row.started_at),
      to: clockField(row.ended_at),
      task: '',
      note: '',
    });
    expect(patch.plan_task_id).toBeNull();
  });

  it('нетронутый интервал даёт пустой патч', () => {
    const row = interval({ note: 'рефакторинг' });
    expect(
      changedFields(row, {
        from: clockField(row.started_at),
        to: clockField(row.ended_at),
        task: '',
        note: 'рефакторинг',
      })
    ).toEqual({});
  });

  it('сдвиг времени не двигает дату', () => {
    const moved = withClock('2026-08-31T08:00:00.000Z', '23:45');
    expect(moved).not.toBeNull();
    expect(new Date(moved as string).getHours()).toBe(23);
    expect(new Date(moved as string).getDate()).toBe(31);
  });

  it('невалидное время не превращается в момент', () => {
    expect(withClock('2026-08-31T08:00:00.000Z', '25:00')).toBeNull();
    expect(withClock('2026-08-31T08:00:00.000Z', 'полдень')).toBeNull();
  });
});
