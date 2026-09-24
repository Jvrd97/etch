// [review:need-review] PHASE-01/20-category-page-chart, #176
// summary: unit tests for chart-data helpers, including units stored on fields

import { describe, expect, it } from 'bun:test';
import type { Field, TableDay } from './api';
import {
  buildChartData,
  buildSeries,
  chartDateRange,
  chartableFields,
  parseCellValue,
  sliceByPeriod,
} from './chart-data';

function makeField(overrides: Partial<Field> & Pick<Field, 'id' | 'name' | 'field_type'>): Field {
  return {
    category_id: 1,
    is_required: false,
    order: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

const kmField = makeField({
  id: 10,
  name: 'Distance',
  field_type: 'number',
  order: 0,
  unit: 'km',
});
const timeField = makeField({ id: 11, name: 'Duration', field_type: 'time', order: 1 });
const notesField = makeField({ id: 12, name: 'Notes', field_type: 'text', order: 2 });
const stepsField = makeField({ id: 13, name: 'Steps', field_type: 'number', order: 3 });

describe('chartableFields', () => {
  it('keeps only number/time fields sorted by order', () => {
    const result = chartableFields([stepsField, notesField, timeField, kmField]);
    expect(result.map((f) => f.id)).toEqual([10, 11, 13]);
  });
});

describe('buildSeries', () => {
  it('uses the field unit instead of guessing it from the field name', () => {
    const field = makeField({
      id: 14,
      name: 'Distance (legacy label)',
      field_type: 'number',
      unit: 'km',
    });

    expect(buildSeries([field])[0]?.unit).toBe('km');
  });

  it('puts km and time on different axes with proper units', () => {
    const series = buildSeries([kmField, timeField]);
    expect(series).toHaveLength(2);
    expect(series[0]).toMatchObject({ key: 'f10', unit: 'km', axis: 'left' });
    expect(series[1]).toMatchObject({ key: 'f11', unit: 'min', axis: 'right' });
  });

  it('keeps same-unit series on the left axis', () => {
    const a = makeField({ id: 1, name: 'Work', field_type: 'number', order: 0, unit: 'h' });
    const b = makeField({ id: 2, name: 'Rest', field_type: 'number', order: 1, unit: 'h' });
    const series = buildSeries([a, b]);
    expect(series.map((s) => s.axis)).toEqual(['left', 'left']);
  });

  it('assigns distinct colors in fixed order', () => {
    const series = buildSeries([kmField, timeField, stepsField]);
    const colors = series.map((s) => s.color);
    expect(new Set(colors).size).toBe(3);
  });
});

describe('parseCellValue', () => {
  it('parses number values', () => {
    expect(parseCellValue('number', '12.5')).toBe(12.5);
    expect(parseCellValue('number', 'abc')).toBeNull();
    expect(parseCellValue('number', null)).toBeNull();
  });

  it('parses HH:MM[:SS] time values into minutes', () => {
    expect(parseCellValue('time', '01:30')).toBe(90);
    expect(parseCellValue('time', '00:45:30')).toBe(45.5);
    expect(parseCellValue('time', 'later')).toBeNull();
  });
});

describe('buildChartData', () => {
  const days: TableDay[] = [
    {
      date: '2026-07-01',
      cells: [
        { category_id: 1, field_id: 10, aggregated_value: '5.2', entry_count: 1 },
        { category_id: 1, field_id: 11, aggregated_value: '00:30', entry_count: 1 },
        { category_id: 2, field_id: 99, aggregated_value: '999', entry_count: 1 },
      ],
    },
    { date: '2026-07-02', cells: [] },
  ];

  it('builds one point per day keyed by field, ignoring other categories', () => {
    const data = buildChartData(days, 1, [kmField, timeField]);
    expect(data).toEqual([
      { date: '2026-07-01', f10: 5.2, f11: 30 },
      { date: '2026-07-02', f10: null, f11: null },
    ]);
  });
});

describe('chartDateRange', () => {
  it('spans MAX_CHART_DAYS ending today', () => {
    const range = chartDateRange(new Date('2026-07-22T12:00:00Z'));
    expect(range).toEqual({ from: '2025-07-23', to: '2026-07-22' });
  });
});

describe('sliceByPeriod', () => {
  const points = Array.from({ length: 40 }, (_, i) => ({ date: `d${i}` }));

  it('keeps the last N days for a fixed period', () => {
    const result = sliceByPeriod(points, '7d');
    expect(result).toHaveLength(7);
    expect(result[0].date).toBe('d33');
  });

  it('keeps everything for all', () => {
    expect(sliceByPeriod(points, 'all')).toHaveLength(40);
  });
});
