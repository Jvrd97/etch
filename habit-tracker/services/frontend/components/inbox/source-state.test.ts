// [review:need-review] PHASE-03/105
// summary: tests for the state of a source — a missing adapter always wins, the class of the last failure picks «нужен вход» or «сломалось», a healthy source has no state, and a moment is written with its day

import { describe, expect, it } from 'bun:test';
import type { SignalSource, SourceErrorClass } from '@/lib/api';
import { CLASS_HINT, moment, sourceState } from '@/components/inbox/source-state';

const source = (overrides: Partial<SignalSource> = {}): SignalSource => ({
  id: 1,
  provider: 'clickup',
  account: 'personal',
  label: null,
  direction: 'read',
  is_active: true,
  poll_interval_s: 900,
  credential_ref: null,
  has_secret: true,
  settings: {},
  has_adapter: true,
  last_polled_at: null,
  cursor_at: null,
  last_ingested: null,
  last_error_code: null,
  last_error_class: null,
  last_error_at: null,
  ...overrides,
});

describe('sourceState', () => {
  it('has no state for a source that works', () => {
    expect(sourceState(source(), true)).toBeNull();
  });

  it('is «not_connected» whenever the adapter is missing, whatever else is recorded', () => {
    expect(sourceState(source(), false)).toBe('not_connected');
    expect(sourceState(source({ last_error_class: 'auth_expired' }), false)).toBe(
      'not_connected'
    );
  });

  it('is «not_connected» for the class the server gives to a stub', () => {
    expect(sourceState(source({ last_error_class: 'not_implemented' }), true)).toBe(
      'not_connected'
    );
  });

  it('is «needs_login» for a missing key or session', () => {
    expect(sourceState(source({ last_error_class: 'needs_login' }), true)).toBe(
      'needs_login'
    );
  });

  it.each<SourceErrorClass>(['auth_expired', 'rate_limited', 'network', 'remote_error'])(
    'is «broken» for %s',
    (errorClass) => {
      expect(sourceState(source({ last_error_class: errorClass }), true)).toBe('broken');
    }
  );

  it('has a next step for each of the six classes', () => {
    const classes: SourceErrorClass[] = [
      'auth_expired',
      'needs_login',
      'rate_limited',
      'network',
      'remote_error',
      'not_implemented',
    ];
    for (const one of classes) expect(CLASS_HINT[one]).toBeTruthy();
  });
});

describe('moment', () => {
  it('writes the day with the time, in the reader’s own zone', () => {
    const at = new Date('2026-10-25T14:03:00Z');
    const two = (value: number) => String(value).padStart(2, '0');
    const expected = `${two(at.getDate())}.${two(at.getMonth() + 1)} ${two(at.getHours())}:${two(at.getMinutes())}`;

    expect(moment('2026-10-25T14:03:00Z')).toBe(expected);
  });

  it('answers an unreadable moment with an empty string', () => {
    expect(moment('not a date')).toBe('');
  });
});
