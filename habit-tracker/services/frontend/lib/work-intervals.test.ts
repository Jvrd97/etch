// [review:need-review] PHASE-03/91
// summary: unit tests for the pure work-interval helpers — a wall clock turned into an instant of the day being edited, an end before its start read as the next morning, an unreadable clock refused rather than guessed, and the agent's proposal shown only where there was one

import { describe, expect, it } from 'bun:test';
import type { WorkInterval } from '@/lib/api';
import {
  RUNNING_LABEL,
  clockOf,
  crossesMidnight,
  momentOf,
  proposedLabel,
  sourceLabel,
  spanLabel,
} from './work-intervals';

const DAY = '2026-08-24';

const INTERVAL: WorkInterval = {
  id: 'i-1',
  day_date: DAY,
  started_at: new Date(2026, 7, 24, 9, 30).toISOString(),
  ended_at: new Date(2026, 7, 24, 13, 0).toISOString(),
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

describe('momentOf', () => {
  it('turns a wall clock into an instant of that day', () => {
    const moment = momentOf(DAY, '09:30');

    expect(moment).not.toBeNull();
    expect(clockOf(moment as string)).toBe('09:30');
    expect(new Date(moment as string).getDate()).toBe(24);
  });

  it('puts an end that crosses midnight on the next morning', () => {
    // Which *day* the interval then belongs to is not decided here: the server
    // asks local_date(), whose boundary hour is a column of the canon.
    const moment = momentOf(DAY, '01:00', true);

    expect(new Date(moment as string).getDate()).toBe(25);
    expect(clockOf(moment as string)).toBe('01:00');
  });

  it('refuses a clock it cannot read rather than guessing one', () => {
    expect(momentOf(DAY, 'после обеда')).toBeNull();
    expect(momentOf(DAY, '25:00')).toBeNull();
    expect(momentOf(DAY, '09:70')).toBeNull();
    expect(momentOf('вчера', '09:30')).toBeNull();
  });
});

describe('crossesMidnight', () => {
  it('is true when the end names an earlier clock than the start', () => {
    expect(crossesMidnight('23:00', '01:00')).toBe(true);
  });

  it('is false for an ordinary interval', () => {
    expect(crossesMidnight('09:30', '13:00')).toBe(false);
  });

  it('treats an equal clock as a full day rather than a zero-length one', () => {
    expect(crossesMidnight('09:00', '09:00')).toBe(true);
  });
});

describe('spanLabel', () => {
  it('reads a closed interval as its two clocks', () => {
    expect(spanLabel(INTERVAL)).toBe('09:30 – 13:00');
  });

  it('says the interval is running rather than showing an empty end', () => {
    expect(spanLabel({ ...INTERVAL, ended_at: null, running: true })).toBe(
      `09:30 – ${RUNNING_LABEL}`
    );
  });
});

describe('proposedLabel', () => {
  it('is null on an interval nobody corrected', () => {
    expect(proposedLabel(INTERVAL)).toBeNull();
  });

  it('shows what the agent proposed on a corrected one', () => {
    const corrected: WorkInterval = {
      ...INTERVAL,
      source: 'corrected',
      auto_started_at: new Date(2026, 7, 24, 9, 0).toISOString(),
      auto_ended_at: new Date(2026, 7, 24, 18, 0).toISOString(),
    };

    expect(proposedLabel(corrected)).toBe('09:00 – 18:00');
  });
});

describe('sourceLabel', () => {
  it('translates the three codes the server speaks', () => {
    expect(sourceLabel('manual')).toBe('руками');
    expect(sourceLabel('agent')).toBe('агент');
    expect(sourceLabel('corrected')).toBe('исправлено');
  });
});
