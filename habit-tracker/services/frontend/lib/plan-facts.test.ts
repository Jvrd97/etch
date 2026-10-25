// [review:need-review] PHASE-03/200
// summary: unit tests for the plan-fact helpers — which field a link defaults to and when the person has to choose, how a typed number or duration is read, how a fact and the progress against a target are worded, and when a write also ticks the line

import { describe, expect, it } from 'bun:test';
import type { Category, Field, PlanItemFacts } from '@/lib/api';
import {
  defaultLinkField,
  factErrorText,
  factValueText,
  historyHref,
  linkStateText,
  markAfterCorrect,
  markAfterRecord,
  markAfterRemove,
  parseFactInput,
  progressText,
} from './plan-facts';

function field(id: number, field_type: Field['field_type'], unit: string | null = null): Field {
  return {
    id,
    category_id: 1,
    name: `f${id}`,
    field_type,
    is_required: false,
    order: id,
    unit,
    created_at: '',
    updated_at: '',
  };
}

function category(fields: Field[], primary: number | null = null): Category {
  return {
    id: 1,
    name: 'Отжимания',
    display_mode: 'form',
    streak_mode: 'build',
    primary_field_id: primary,
    is_active: true,
    created_at: '',
    updated_at: '',
    fields,
  };
}

function facts(over: Partial<PlanItemFacts> = {}): PlanItemFacts {
  return {
    item_id: 'i1',
    link: {
      category_id: 1,
      category_name: 'Отжимания',
      category_active: true,
      field_id: 11,
      field_name: 'Повторения',
      field_type: 'number',
      unit: 'раз',
      target_value: 300,
      state: 'ok',
      fields: [{ id: 11, name: 'Повторения', field_type: 'number', unit: 'раз' }],
    },
    entries: [],
    total: null,
    done: false,
    progress: 'none',
    ...over,
  };
}

function entry(entry_id: number, value: string): PlanItemFacts['entries'][number] {
  return {
    entry_id,
    entry_date: '2026-08-31',
    values: [{ field_id: 11, value }],
    created_at: '',
    updated_at: '',
  };
}

describe('defaultLinkField', () => {
  it('takes the one field a fact can be typed into', () => {
    expect(defaultLinkField(category([field(11, 'number'), field(12, 'text')]))).toBe(11);
  });

  it('takes the primary field when it can hold a fact', () => {
    expect(
      defaultLinkField(category([field(11, 'number'), field(12, 'duration')], 12))
    ).toBe(12);
  });

  it('asks rather than guesses when two fields could hold it', () => {
    expect(
      defaultLinkField(category([field(11, 'number'), field(12, 'number')]))
    ).toBeNull();
  });
});

describe('parseFactInput', () => {
  it('reads a number with a comma as a decimal point', () => {
    expect(parseFactInput('number', '3,5')).toBe(3.5);
  });

  it('reads a duration as whole seconds', () => {
    expect(parseFactInput('duration', '1:30')).toBe(5400);
  });

  it('refuses text that is not a number', () => {
    expect(parseFactInput('number', 'много')).toBeNull();
    expect(parseFactInput('number', '')).toBeNull();
  });
});

describe('wording', () => {
  it('words a number with its unit, a box as a statement, a duration as h:m', () => {
    expect(factValueText('number', '300', 'раз')).toBe('300 раз');
    expect(factValueText('boolean', 'true', null)).toBe('было');
    expect(factValueText('duration', '5400', null)).toBe('1h 30m');
  });

  it('says partial as «из», never as done', () => {
    expect(progressText(facts({ total: 100, progress: 'partial' }))).toBe(
      'Сделано 100 из 300 раз'
    );
  });

  it('tells a target from a fact before anything is recorded', () => {
    expect(progressText(facts())).toBe('Цель 300 раз, пока не записано');
  });

  it('names a broken link instead of offering an input', () => {
    expect(linkStateText('ok')).toBeNull();
    expect(linkStateText('category_archived')).toContain('архив');
    expect(linkStateText('field_missing')).toContain('поле');
  });

  it('turns a list of reasons into one sentence', () => {
    // The shape `APIError` arrives in; built by hand so this suite needs no
    // value from `@/lib/api`, which other suites mock.
    const error = Object.assign(new Error('An error occurred'), {
      detail: {
        error: 'fact_invalid',
        reasons: ['единица поля 11 не совпадает с присланной'],
      },
    });
    expect(factErrorText(error)).toContain('единица поля 11');
  });

  it('points at the category history on each screen', () => {
    expect(historyHref(5, false)).toBe('/categories/5');
    expect(historyHref(5, true)).toBe('/m/categories/5');
  });
});

describe('when a write also ticks the line', () => {
  it('ticks once the target is reached, not before', () => {
    expect(markAfterRecord(facts({ total: 200 }), 100)).toBe('done');
    expect(markAfterRecord(facts({ total: 100 }), 100)).toBeNull();
  });

  it('ticks a line without a target, and a box set to «было»', () => {
    const noTarget = facts();
    noTarget.link = { ...noTarget.link, target_value: null };
    expect(markAfterRecord(noTarget, 3)).toBe('done');

    const box = facts();
    box.link = { ...box.link, field_type: 'boolean', target_value: null };
    expect(markAfterRecord(box, true)).toBe('done');
    expect(markAfterRecord(box, false)).toBeNull();
  });

  it('a correction counts the corrected entry once', () => {
    const written = facts({
      total: 300,
      entries: [
        {
          entry_id: 7,
          entry_date: '2026-08-31',
          values: [{ field_id: 11, value: '300' }],
          created_at: '',
          updated_at: '',
        },
      ],
    });
    expect(markAfterCorrect(written, 7, 200)).toBe('unmark');
    expect(markAfterCorrect(written, 7, 300)).toBe('done');
  });

  it('a box corrected to «не было» takes «сделано» back unless another entry says «было»', () => {
    const box = facts({ entries: [entry(7, 'true')] });
    box.link = { ...box.link, field_type: 'boolean', target_value: null };
    expect(markAfterCorrect(box, 7, false)).toBe('unmark');

    box.entries = [entry(7, 'true'), entry(8, 'true')];
    expect(markAfterCorrect(box, 7, false)).toBeNull();
  });

  it('a delete takes «сделано» back once what is left no longer does the line', () => {
    expect(markAfterRemove(facts({ total: 300, entries: [entry(7, '300')] }), 7)).toBe('unmark');

    const two = facts({ total: 300, entries: [entry(7, '150'), entry(8, '150')] });
    expect(markAfterRemove(two, 7)).toBe('unmark');
    two.link = { ...two.link, target_value: 100 };
    expect(markAfterRemove(two, 7)).toBeNull();

    const box = facts({ entries: [entry(7, 'true')] });
    box.link = { ...box.link, field_type: 'boolean', target_value: null };
    expect(markAfterRemove(box, 7)).toBe('unmark');
  });
});
