// [review:need-review] #176
// summary: unit formatting and field-specific quick-step selection contracts

import { describe, expect, test } from 'bun:test';
import { formatValue, quickStepsForField } from './format-value';

describe('field value presentation', () => {
  test('formats optional units and selects configured or default steps', () => {
    expect(formatValue(42, null)).toBe('42');
    expect(formatValue('42', 'reps')).toBe('42 reps');
    expect(quickStepsForField([-250, 250, 500])).toEqual([-250, 250, 500]);
    expect(quickStepsForField(null)).toEqual([-5, -1, 1, 5]);
  });
});
