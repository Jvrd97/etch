// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, #176
// summary: unit tests for the entry draft <-> payload helpers shared by the desktop forms and the mobile sheet

import { describe, expect, it } from 'bun:test';
import type { Category, Entry, Field } from './api';
import { UNNAMED_FIELD_LABEL, draftValuesFromEntry, labelledValues, toEntryValues } from './entry-values';

const TIMESTAMP = '2026-07-24T00:00:00Z';

function field(id: number, name: string): Field {
  return {
    id,
    category_id: 1,
    name,
    field_type: 'text',
    is_required: false,
    order: id,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
  };
}

const CATEGORY: Category = {
  id: 1,
  name: 'Sleep',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [field(7, 'Hours'), field(8, 'Quality')],
};

const ENTRY: Entry = {
  id: 10,
  category_id: 1,
  entry_date: '2026-07-24',
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  values: [
    { id: 1, entry_id: 10, field_id: 7, value: '8' },
    { id: 2, entry_id: 10, field_id: 8, value: 'good' },
  ],
};

describe('draftValuesFromEntry', () => {
  it('keys the stored values by field id', () => {
    expect(draftValuesFromEntry(ENTRY)).toEqual({ 7: '8', 8: 'good' });
  });

  it('is empty for an entry with no values yet', () => {
    expect(draftValuesFromEntry({ ...ENTRY, values: [] })).toEqual({});
  });
});

describe('toEntryValues', () => {
  it('emits one value per category field, in field order', () => {
    expect(toEntryValues(CATEGORY, { 7: '8', 8: 'good' })).toEqual([
      { field_id: 7, value: '8' },
      { field_id: 8, value: 'good' },
    ]);
  });

  it('sends an empty string for a field the user left blank', () => {
    expect(toEntryValues(CATEGORY, { 7: '8' })).toEqual([
      { field_id: 7, value: '8' },
      { field_id: 8, value: '' },
    ]);
  });

  it('drops a draft value whose field no longer belongs to the category', () => {
    expect(toEntryValues({ ...CATEGORY, fields: [field(7, 'Hours')] }, { 7: '8', 99: 'x' })).toEqual(
      [{ field_id: 7, value: '8' }]
    );
  });
});

describe('labelledValues', () => {
  it('formats a resolved field value with its optional unit', () => {
    const withUnit: Category = {
      ...CATEGORY,
      fields: [{ ...CATEGORY.fields[0], unit: 'h' }, CATEGORY.fields[1]],
    };
    expect(labelledValues(withUnit, ENTRY)[0].value).toBe('8 h');
    expect(labelledValues(CATEGORY, ENTRY)[0].value).toBe('8');
  });
  it('names every stored value after its field, in stored order', () => {
    expect(labelledValues(CATEGORY, ENTRY)).toEqual([
      { id: 1, label: 'Hours', value: '8' },
      { id: 2, label: 'Quality', value: 'good' },
    ]);
  });

  it('falls back to a placeholder label when the field is gone', () => {
    const shrunk: Category = { ...CATEGORY, fields: [field(7, 'Hours')] };
    expect(labelledValues(shrunk, ENTRY)[1]).toEqual({
      id: 2,
      label: UNNAMED_FIELD_LABEL,
      value: 'good',
    });
  });

  it('labels nothing when the category itself was deleted', () => {
    expect(labelledValues(undefined, ENTRY).map((value) => value.label)).toEqual([
      UNNAMED_FIELD_LABEL,
      UNNAMED_FIELD_LABEL,
    ]);
  });

  it('is empty for an entry without values', () => {
    expect(labelledValues(CATEGORY, { ...ENTRY, values: [] })).toEqual([]);
  });
});
