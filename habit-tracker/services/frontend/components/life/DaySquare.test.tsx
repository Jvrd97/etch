// [review:need-review] PHASE-03/94
// summary: component tests for the day square — the three states differ by fill and not only by shade, an unclosed day is not painted like a lost one, and every square is a link to /day/{date}

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import DaySquare from './DaySquare';
import type { DayStatus } from '@/lib/life';

function show(status: DayStatus, date = '2026-08-30') {
  render(<DaySquare date={date} status={status} />);
  return screen.getByRole('link');
}

afterEach(() => {
  cleanup();
});

describe('DaySquare', () => {
  it('paints the three states differently', () => {
    // The acceptance case: «квадрат дня без итога выглядит иначе, чем квадрат
    // проигранного дня». Won and lost are filled, an unclosed day is an outline
    // — a difference of shape rather than of brightness.
    const won = show('won', '2026-08-28').className;
    cleanup();
    const lost = show('lost', '2026-08-29').className;
    cleanup();
    const open = show('open', '2026-08-30').className;

    expect(won).not.toBe(lost);
    expect(open).not.toBe(lost);
    expect(open).not.toBe(won);
    expect(open).toContain('bg-transparent');
    expect(lost).toContain('bg-text-disabled');
    expect(won).toContain('bg-lime');
  });

  it('links to the day it stands for', () => {
    const square = show('won');

    expect(square.getAttribute('href')).toBe('/day/2026-08-30');
  });

  it('says what state it is in, in words, for the tooltip and the reader', () => {
    const square = show('open');

    expect(square.getAttribute('aria-label')).toContain('не закрыт');
  });

  it('carries the state as data so a grid can be read without colours', () => {
    const square = show('lost');

    expect(square.getAttribute('data-status')).toBe('lost');
  });
});
