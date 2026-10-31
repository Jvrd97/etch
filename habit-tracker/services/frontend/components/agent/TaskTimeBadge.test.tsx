// [review:need-review] PHASE-03/166
// summary: component tests of the task-time chip, of the day's summary blocks (done with no trace, work outside the plan, the thirty-day share and its honest window caption) and of the pure helpers behind them

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { TaskTimeDay } from '@/lib/api';
import { doneMarksKey, minutesByItem, shareWindowCaption } from '@/lib/task-time';
import TaskTimeBadge from './TaskTimeBadge';
import TaskTimeSummary from './TaskTimeSummary';

afterEach(() => {
  cleanup();
});

function day(overrides: Partial<TaskTimeDay> = {}): TaskTimeDay {
  return {
    date: '2026-10-31',
    today: '2026-10-31',
    tasks: [],
    untasked_minutes: 0,
    other_linked_minutes: 0,
    long_untasked: [],
    done_without_traces: [],
    commits_checked: false,
    untasked_share: { window_days: 30, observed_days: 30, intervals: 0, untasked: 0, share: null },
    ...overrides,
  };
}

describe('TaskTimeBadge', () => {
  it('prints the time of a task in hours and minutes', () => {
    render(<TaskTimeBadge minutes={90} />);
    expect(screen.getByText('1 ч 30 мин')).toBeTruthy();
  });

  it('draws nothing for a task with no time', () => {
    const { container } = render(<TaskTimeBadge minutes={0} />);
    expect(container.innerHTML).toBe('');
    cleanup();
    const missing = render(<TaskTimeBadge minutes={undefined} />);
    expect(missing.container.innerHTML).toBe('');
  });
});

describe('TaskTimeSummary', () => {
  it('draws nothing before the first answer or when there is nothing to say', () => {
    expect(render(<TaskTimeSummary taskTime={null} />).container.innerHTML).toBe('');
    cleanup();
    expect(render(<TaskTimeSummary taskTime={day()} />).container.innerHTML).toBe('');
  });

  it('lists a task ticked done with no trace and says the web cannot see commits', () => {
    render(
      <TaskTimeSummary
        taskTime={day({ done_without_traces: [{ plan_item_id: 'a', title: 'Починить импорт' }] })}
      />
    );
    expect(screen.getByText('Отмечено сделанным, следов нет')).toBeTruthy();
    expect(screen.getByText('Починить импорт')).toBeTruthy();
    expect(screen.getByText(/Коммиты здесь не видны/)).toBeTruthy();
  });

  it('says commits were looked at when they were', () => {
    render(
      <TaskTimeSummary
        taskTime={day({
          commits_checked: true,
          done_without_traces: [{ plan_item_id: 'a', title: 'Починить импорт' }],
        })}
      />
    );
    expect(screen.getByText('Ни интервала, ни коммита по этим задачам нет.')).toBeTruthy();
  });

  it('shows work outside the plan with its length and application', () => {
    render(
      <TaskTimeSummary
        taskTime={day({
          long_untasked: [
            {
              interval_id: 7,
              started_at: '2026-10-31T10:00:00Z',
              ended_at: '2026-10-31T10:45:00Z',
              minutes: 45,
              app_name: 'Safari',
            },
          ],
        })}
      />
    );
    expect(screen.getByText('Работа вне плана')).toBeTruthy();
    expect(screen.getByText(/45 мин · Safari/)).toBeTruthy();
  });

  it('shows the time tied by another id and says it is neither a plan task nor a gap', () => {
    render(<TaskTimeSummary taskTime={day({ other_linked_minutes: 90 })} />);
    expect(screen.getByText('Привязано не к задаче плана')).toBeTruthy();
    expect(screen.getByText('1 ч 30 мин')).toBeTruthy();
    expect(screen.getByText(/не пункт плана и не «без задачи»/)).toBeTruthy();
  });

  it('captions a short window with the days it really covers', () => {
    render(
      <TaskTimeSummary
        taskTime={day({
          untasked_share: { window_days: 30, observed_days: 4, intervals: 8, untasked: 5, share: 0.625 },
        })}
      />
    );
    expect(screen.getByText('63%')).toBeTruthy();
    expect(screen.getByText(/за 4 дня данных из 30/)).toBeTruthy();
  });

  it('names a full window as thirty days', () => {
    expect(
      shareWindowCaption({ window_days: 30, observed_days: 30, intervals: 3, untasked: 1, share: 1 / 3 })
    ).toBe('за 30 дней');
  });
});

describe('minutesByItem', () => {
  it('keys the minutes by plan item', () => {
    const map = minutesByItem(day({ tasks: [{ plan_item_id: 'x', title: 't', minutes: 20 }] }));
    expect(map.get('x')).toBe(20);
    expect(minutesByItem(null).size).toBe(0);
  });
});

describe('doneMarksKey', () => {
  it('changes with the done marks only and is null while a mark is being written', () => {
    const marks = new Map([
      ['b', { state: 'done' }],
      ['a', { state: 'done' }],
      ['c', { state: 'failed' }],
      ['d', { state: null }],
    ]);
    expect(doneMarksKey(marks, new Set())).toBe('a,b');
    expect(doneMarksKey(marks, new Set(['a']))).toBeNull();
  });
});
