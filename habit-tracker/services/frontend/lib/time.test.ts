// [review:need-review] PHASE-03/priemka-5.7
// summary: tests of the single clock reading — the hour a moment shows in the reader's zone, the window built from two ends, and the empty answer an unreadable moment gets instead of NaN:NaN

import { describe, expect, it } from 'bun:test';
import { clock, clockRange } from '@/lib/time';

describe('clock', () => {
  it('reads a moment as the wall clock of the reader', () => {
    const at = new Date(2026, 7, 24, 9, 30);

    expect(clock(at.toISOString())).toBe('09:30');
  });

  it('pads both halves so the column stays a column', () => {
    const at = new Date(2026, 7, 24, 1, 5);

    expect(clock(at.toISOString())).toBe('01:05');
  });

  it('answers with nothing on a moment it cannot read', () => {
    // Не «NaN:NaN» и не сама строка: и то и другое ставит в место часов
    // то, что часами не является, — в том числе в поле, которое человек правит.
    expect(clock('вчера')).toBe('');
    expect(clock('')).toBe('');
  });
});

describe('clockRange', () => {
  it('joins two ends into the window the screen prints', () => {
    const from = new Date(2026, 7, 24, 10, 0);
    const to = new Date(2026, 7, 24, 11, 30);

    expect(clockRange(from.toISOString(), to.toISOString())).toBe('10:00-11:30');
  });
});
