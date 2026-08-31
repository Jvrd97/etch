// [review:need-review] PHASE-03/91
// summary: component tests for the work block — a day with no intervals says «время не измерено» instead of nought, a running interval reads as running and can be stopped, a corrected interval shows its value and the agent's beside it, and a typed 09:30-13:00 reaches the caller as one interval of that day

import { afterEach, describe, expect, it, mock } from 'bun:test';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import type { WorkDay, WorkInterval } from '@/lib/api';
import { NOT_MEASURED, RUNNING_LABEL, clockOf } from '@/lib/work-intervals';
import WorkIntervals, {
  ADD_INTERVAL,
  EMPTY_HINT,
  FROM_LABEL,
  STOP_INTERVAL,
  TO_LABEL,
} from './WorkIntervals';

const DAY = '2026-08-24';

/** A local wall-clock moment of the day, as the browser would build one. */
function at(hours: number, minutes = 0): string {
  return new Date(2026, 7, 24, hours, minutes).toISOString();
}

const CLOSED: WorkInterval = {
  id: 'i-1',
  day_date: DAY,
  started_at: at(9, 30),
  ended_at: at(13),
  running: false,
  minutes: 210,
  source: 'manual',
  mode: 'work',
  auto_started_at: null,
  auto_ended_at: null,
  app_bundle_id: null,
  note: null,
  edited_at: null,
};

function day(patch: Partial<WorkDay> = {}): WorkDay {
  return {
    day_date: DAY,
    intervals: [CLOSED],
    work_minutes: 210,
    running: false,
    ...patch,
  };
}

type AddHandler = (started_at: string, ended_at: string | null) => Promise<void>;
type StopHandler = (intervalId: string, ended_at: string) => Promise<void>;
type RemoveHandler = (intervalId: string) => Promise<void>;

interface Handlers {
  onAdd?: AddHandler;
  onStop?: StopHandler;
  onRemove?: RemoveHandler;
}

const noAdd: AddHandler = () => Promise.resolve();
const noStop: StopHandler = () => Promise.resolve();
const noRemove: RemoveHandler = () => Promise.resolve();

function show(work: WorkDay, handlers: Handlers = {}) {
  render(
    <WorkIntervals
      work={work}
      saving={new Set()}
      error={null}
      onAdd={handlers.onAdd ?? noAdd}
      onStop={handlers.onStop ?? noStop}
      onRemove={handlers.onRemove ?? noRemove}
    />
  );
}

afterEach(() => {
  cleanup();
});

describe('WorkIntervals', () => {
  it('says «время не измерено» rather than nought when the day has none', () => {
    // A zero would read as "работал ноль минут" — the exact confusion the null
    // exists to prevent, and the reason the day skips the overtime check.
    show(day({ intervals: [], work_minutes: null }));

    expect(screen.getByText(NOT_MEASURED)).toBeDefined();
    expect(screen.getByText(EMPTY_HINT)).toBeDefined();
  });

  it('shows the interval and the sum it makes', () => {
    show(day());

    expect(screen.getByText(/09:30 – 13:00/)).toBeDefined();
    // 210 minutes read the way the canon itself is written.
    expect(screen.getAllByText(/3 ч 30 мин/).length).toBeGreaterThan(0);
  });

  it('reads a running interval as running and offers to stop it', async () => {
    const onStop = mock<StopHandler>(() => Promise.resolve());
    const running: WorkInterval = {
      ...CLOSED,
      id: 'i-2',
      ended_at: null,
      running: true,
      minutes: 45,
    };
    show(
      day({ intervals: [running], work_minutes: 45, running: true }),
      { onStop }
    );

    expect(screen.getAllByText(new RegExp(RUNNING_LABEL)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText(STOP_INTERVAL));

    await waitFor(() => expect(onStop).toHaveBeenCalled());
    expect(onStop.mock.calls[0][0]).toBe('i-2');
  });

  it('shows a corrected interval next to what the agent proposed', () => {
    // Приёмка: исправленный интервал показывает и новое значение, и предложение.
    const corrected: WorkInterval = {
      ...CLOSED,
      id: 'i-3',
      started_at: at(9),
      ended_at: at(16),
      minutes: 420,
      source: 'corrected',
      auto_started_at: at(9),
      auto_ended_at: at(18),
      edited_at: at(19),
    };
    show(day({ intervals: [corrected], work_minutes: 420 }));

    expect(screen.getByText(/09:00 – 16:00/)).toBeDefined();
    expect(screen.getByText(/Агент предлагал: 09:00 – 18:00/)).toBeDefined();
    expect(screen.getByText('исправлено')).toBeDefined();
  });

  it('sends a typed 09:30-13:00 as one interval of the day', async () => {
    // The acceptance case, on the screen side: the person types the clock they
    // lived by and the block hands the caller two moments of that day.
    const onAdd = mock<AddHandler>(() => Promise.resolve());
    show(day({ intervals: [], work_minutes: null }), { onAdd });

    fireEvent.change(screen.getByLabelText(FROM_LABEL), {
      target: { value: '09:30' },
    });
    fireEvent.change(screen.getByLabelText(TO_LABEL), {
      target: { value: '13:00' },
    });
    fireEvent.click(screen.getByText(ADD_INTERVAL));

    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    const [started, ended] = onAdd.mock.calls[0];
    expect(clockOf(started)).toBe('09:30');
    expect(clockOf(ended as string)).toBe('13:00');
  });

  it('reads an end before its start as the next morning, not as an error', async () => {
    // 23:00 → 01:00 is one interval; which day it belongs to stays the
    // server's answer, and this only stops it from ending before it began.
    const onAdd = mock<AddHandler>(() => Promise.resolve());
    show(day({ intervals: [], work_minutes: null }), { onAdd });

    fireEvent.change(screen.getByLabelText(FROM_LABEL), {
      target: { value: '23:00' },
    });
    fireEvent.change(screen.getByLabelText(TO_LABEL), {
      target: { value: '01:00' },
    });
    fireEvent.click(screen.getByText(ADD_INTERVAL));

    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    const [started, ended] = onAdd.mock.calls[0];
    expect(new Date(ended as string).getTime()).toBeGreaterThan(
      new Date(started).getTime()
    );
    expect(clockOf(ended as string)).toBe('01:00');
  });

  it('adds an interval with no end when only the start is typed', async () => {
    const onAdd = mock<AddHandler>(() => Promise.resolve());
    show(day({ intervals: [], work_minutes: null }), { onAdd });

    fireEvent.change(screen.getByLabelText(FROM_LABEL), {
      target: { value: '10:00' },
    });
    fireEvent.click(screen.getByText(ADD_INTERVAL));

    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    expect(onAdd.mock.calls[0][1]).toBeNull();
  });

  it('refuses a clock it cannot read instead of sending it', () => {
    const onAdd = mock<AddHandler>(() => Promise.resolve());
    show(day({ intervals: [], work_minutes: null }), { onAdd });

    fireEvent.change(screen.getByLabelText(FROM_LABEL), {
      target: { value: 'после обеда' },
    });
    fireEvent.click(screen.getByText(ADD_INTERVAL));

    expect(onAdd).not.toHaveBeenCalled();
  });
});
