// [review:need-review] PHASE-01/60-quick-plus-tap-adds-one
// summary: tests for quickAddAmount — the tap-to-log parser (empty means 1, zero and junk mean nothing)

import { describe, expect, it } from 'bun:test';
import { quickAddAmount } from './quick-add';

describe('quickAddAmount', () => {
  it('logs 1 when the field is empty', () => {
    expect(quickAddAmount('')).toBe(1);
  });

  it('logs 1 when the field holds only whitespace', () => {
    expect(quickAddAmount('   ')).toBe(1);
  });

  it('logs the typed number', () => {
    expect(quickAddAmount('250')).toBe(250);
    expect(quickAddAmount('0.5')).toBe(0.5);
    expect(quickAddAmount(' 12 ')).toBe(12);
  });

  it('logs negative numbers so a typo can be corrected without the journal', () => {
    expect(quickAddAmount('-250')).toBe(-250);
  });

  it('logs nothing for zero — a zero-valued entry is never what the tap meant', () => {
    expect(quickAddAmount('0')).toBeNull();
    expect(quickAddAmount('-0')).toBeNull();
    expect(quickAddAmount('0.00')).toBeNull();
  });

  it('logs nothing for non-numeric input, silently', () => {
    expect(quickAddAmount('abc')).toBeNull();
    expect(quickAddAmount('1,5')).toBeNull();
    expect(quickAddAmount('-')).toBeNull();
    expect(quickAddAmount('Infinity')).toBeNull();
  });

  // A `type="number"` control hides unparseable text: the DOM reports an empty
  // `value` and raises `validity.badInput` instead. Without that second signal
  // "abc" would be indistinguishable from an untouched field and would log a 1.
  it('logs nothing when the control holds text it refused to parse', () => {
    expect(quickAddAmount('', { hasBadInput: true })).toBeNull();
  });

  it('still logs 1 for a genuinely empty control', () => {
    expect(quickAddAmount('', { hasBadInput: false })).toBe(1);
  });
});
