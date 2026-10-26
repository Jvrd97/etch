// [review:need-review] PHASE-03/220
// summary: tests for the words and numbers of the Claude Code block — compact token counts, the caption that tells a session across the boundary counts whole on its start day

import { describe, expect, it } from 'bun:test';
import { boundaryCaption, formatTokens } from './claude-usage';

describe('formatTokens', () => {
  it('writes small counts whole and larger ones with a unit', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(950)).toBe('950');
    expect(formatTokens(12_400)).toBe('12,4 тыс');
    expect(formatTokens(1_250_000)).toBe('1,3 млн');
    expect(formatTokens(3_400_000_000)).toBe('3,4 млрд');
  });

  it('does not round 999 950 up to a thousand thousand', () => {
    expect(formatTokens(999_950)).toBe('1 млн');
  });
});

describe('boundaryCaption', () => {
  it('always says a session counts whole on its start day', () => {
    expect(boundaryCaption(0)).toContain('целиком');
    expect(boundaryCaption(0)).toContain('день начала');
  });

  it('names how many sessions of the day ran past the boundary', () => {
    expect(boundaryCaption(1)).toContain('после границы суток: 1.');
    expect(boundaryCaption(3)).toContain('после границы суток: 3.');
    expect(boundaryCaption(3)).toContain('целиком на день начала');
  });
});
