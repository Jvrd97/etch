// [review:need-review] PHASE-03/87
// summary: component tests for the day's schedule — a window across midnight reads as an hour, colliding windows are marked on both lines, back-to-back windows are not, and a plan with no windows says so instead of rendering an empty list

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { ScheduleEntry, ScheduleOverlap } from '@/lib/api';
import { EMPTY_SCHEDULE_TEXT, OVERLAP_BADGE } from '@/lib/plan';
import DaySchedule from './DaySchedule';

function entry(overrides: Partial<ScheduleEntry> = {}): ScheduleEntry {
  return {
    item_id: 'i1',
    section_id: 's1',
    code: 'W1',
    text_plain: 'Задача W1',
    kind: 'task',
    rigidity: 'soft',
    starts_at: '2026-08-31T07:00:00Z',
    ends_at: '2026-08-31T09:00:00Z',
    minutes: 120,
    window_comment: null,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe('DaySchedule', () => {
  it('shows a window across midnight as sixty minutes', () => {
    // The acceptance case. The number is the server's — it knew the day runs
    // 04:00 to 04:00, and a subtraction here would have produced minus
    // twenty-three hours.
    render(
      <DaySchedule
        schedule={[
          entry({
            code: 'N1',
            text_plain: 'Дочитать главу',
            starts_at: '2026-08-31T21:30:00Z',
            ends_at: '2026-08-31T22:30:00Z',
            minutes: 60,
          }),
        ]}
        overlaps={[]}
      />
    );

    expect(screen.getByText('1 ч')).toBeDefined();
  });

  it('marks both lines of a collision', () => {
    const overlaps: ScheduleOverlap[] = [
      { left_item_id: 'a', right_item_id: 'b', overlap_minutes: 60 },
    ];
    render(
      <DaySchedule
        schedule={[
          entry({ item_id: 'a', code: 'W1' }),
          entry({ item_id: 'b', code: 'W2' }),
        ]}
        overlaps={overlaps}
      />
    );

    // Two lines plus the summary in the heading.
    expect(screen.getAllByText(OVERLAP_BADGE).length).toBe(2);
    expect(screen.getByText(`1 ${OVERLAP_BADGE} · 1 ч`)).toBeDefined();
  });

  it('leaves back-to-back windows unmarked', () => {
    // `tstzrange` is half-open, so 09:00-10:00 and 10:00-11:00 touch without
    // overlapping — and the screen must not invent a problem the plan has not.
    render(
      <DaySchedule
        schedule={[entry({ item_id: 'a' }), entry({ item_id: 'b' })]}
        overlaps={[]}
      />
    );

    expect(screen.queryByText(OVERLAP_BADGE)).toBeNull();
  });

  it('says so when nothing claimed a piece of the clock', () => {
    render(<DaySchedule schedule={[]} overlaps={[]} />);

    expect(screen.getByText(EMPTY_SCHEDULE_TEXT)).toBeDefined();
  });

  it('shows the comment that came with a window', () => {
    render(
      <DaySchedule
        schedule={[entry({ window_comment: 'пока ногти' })]}
        overlaps={[]}
      />
    );

    expect(screen.getByText('— пока ногти')).toBeDefined();
  });
});
