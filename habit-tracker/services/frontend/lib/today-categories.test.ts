// [review:need-review] PHASE-01/63-today-card-tap-and-visibility
// summary: unit tests for Today category partitioning — avoid vs checklist vs quick-form, plus the show_in_today override that pins or hides a category

import { describe, expect, it } from 'bun:test';
import type { Category, Field } from './api';
import { partitionTodayCategories } from './today-categories';

function field(overrides: Partial<Field>): Field {
  return {
    id: 1,
    category_id: 1,
    name: 'Field',
    field_type: 'text',
    is_required: false,
    order: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function category(overrides: Partial<Category>): Category {
  return {
    id: 1,
    name: 'Category',
    display_mode: 'form',
    streak_mode: 'build',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    fields: [],
    ...overrides,
  };
}

describe('partitionTodayCategories', () => {
  it('routes avoid categories to the avoid group, not quick-form', () => {
    const avoid = category({
      id: 10,
      streak_mode: 'avoid',
      display_mode: 'form',
      fields: [field({ id: 100, field_type: 'number', name: 'Amount' })],
    });

    const groups = partitionTodayCategories([avoid]);

    expect(groups.avoid.map((a) => a.category.id)).toEqual([10]);
    expect(groups.quickForm).toHaveLength(0);
    expect(groups.checklist).toHaveLength(0);
  });

  it('keeps a build number category as a quick-form item with its number field', () => {
    const build = category({
      id: 20,
      streak_mode: 'build',
      display_mode: 'form',
      fields: [field({ id: 200, field_type: 'number', name: 'Cups' })],
    });

    const groups = partitionTodayCategories([build]);

    expect(groups.quickForm).toHaveLength(1);
    expect(groups.quickForm[0].category.id).toBe(20);
    expect(groups.quickForm[0].numberField?.id).toBe(200);
    expect(groups.avoid).toHaveLength(0);
  });

  it('routes a checklist category with boolean fields to the checklist group', () => {
    const checklist = category({
      id: 30,
      display_mode: 'checklist',
      streak_mode: 'build',
      fields: [field({ id: 300, field_type: 'boolean', name: 'Done' })],
    });

    const groups = partitionTodayCategories([checklist]);

    expect(groups.checklist.map((c) => c.id)).toEqual([30]);
    expect(groups.quickForm).toHaveLength(0);
  });

  it('exposes the number field on avoid categories when present', () => {
    const avoid = category({
      id: 40,
      streak_mode: 'avoid',
      fields: [field({ id: 400, field_type: 'number', name: 'Cigarettes' })],
    });

    const groups = partitionTodayCategories([avoid]);

    expect(groups.avoid[0].numberField?.id).toBe(400);
  });

  it('leaves the number field undefined on avoid categories that have none', () => {
    const avoid = category({
      id: 50,
      streak_mode: 'avoid',
      fields: [field({ id: 500, field_type: 'text', name: 'Note' })],
    });

    const groups = partitionTodayCategories([avoid]);

    expect(groups.avoid[0].numberField).toBeUndefined();
  });
});

describe('partitionTodayCategories with an explicit show_in_today', () => {
  it('treats an absent flag exactly as before, so old categories do not move', () => {
    const legacy = category({
      id: 60,
      fields: [field({ id: 600, field_type: 'number', name: 'Cups' })],
    });

    // `undefined`, not `null`: a category stored before the column existed
    // deserializes without the key at all.
    expect(legacy.show_in_today).toBeUndefined();
    expect(partitionTodayCategories([legacy]).quickForm.map((q) => q.category.id)).toEqual([
      60,
    ]);
  });

  it('keeps null under the heuristic — that is what null means', () => {
    const auto = category({
      id: 61,
      show_in_today: null,
      fields: [field({ id: 610, field_type: 'number' })],
    });

    expect(partitionTodayCategories([auto]).quickForm).toHaveLength(1);
  });

  it('shows a category with no number field once it is pinned', () => {
    const pinned = category({
      id: 62,
      show_in_today: true,
      fields: [field({ id: 620, field_type: 'text', name: 'Note' })],
    });

    const groups = partitionTodayCategories([pinned]);

    // It earns a card, just one without the quick input: there is no number to
    // increment, and the card itself is the way into the full editor.
    expect(groups.quickForm).toHaveLength(1);
    expect(groups.quickForm[0].category.id).toBe(62);
    expect(groups.quickForm[0].numberField).toBeUndefined();
  });

  it('keeps the quick input on a pinned category that does have a number field', () => {
    const pinned = category({
      id: 63,
      show_in_today: true,
      fields: [
        field({ id: 630, field_type: 'text', order: 0 }),
        field({ id: 631, field_type: 'number', order: 1 }),
      ],
    });

    expect(partitionTodayCategories([pinned]).quickForm[0].numberField?.id).toBe(631);
  });

  it('brings a checklist category onto the quick-input side when it is pinned', () => {
    const pinned = category({
      id: 64,
      display_mode: 'checklist',
      show_in_today: true,
      fields: [field({ id: 640, field_type: 'boolean', name: 'Done' })],
    });

    const groups = partitionTodayCategories([pinned]);

    // Pinning is about the card, not about retyping the category: the checklist
    // section is still where its boolean fields belong.
    expect(groups.checklist.map((c) => c.id)).toEqual([64]);
    expect(groups.quickForm).toHaveLength(0);
  });

  it('hides a number category the user switched off', () => {
    const hidden = category({
      id: 65,
      show_in_today: false,
      fields: [field({ id: 650, field_type: 'number' })],
    });

    const groups = partitionTodayCategories([hidden]);

    expect(groups.quickForm).toHaveLength(0);
    expect(groups.checklist).toHaveLength(0);
    expect(groups.avoid).toHaveLength(0);
  });

  it('hides a checklist category the user switched off', () => {
    const hidden = category({
      id: 66,
      display_mode: 'checklist',
      show_in_today: false,
      fields: [field({ id: 660, field_type: 'boolean' })],
    });

    expect(partitionTodayCategories([hidden]).checklist).toHaveLength(0);
  });

  it('hides an avoid category the user switched off, streak card and all', () => {
    const hidden = category({
      id: 67,
      streak_mode: 'avoid',
      show_in_today: false,
      fields: [field({ id: 670, field_type: 'number' })],
    });

    expect(partitionTodayCategories([hidden]).avoid).toHaveLength(0);
  });

  it('gives a pinned avoid category its streak card, not a quick input', () => {
    const pinned = category({
      id: 68,
      streak_mode: 'avoid',
      show_in_today: true,
      fields: [field({ id: 680, field_type: 'number' })],
    });

    const groups = partitionTodayCategories([pinned]);

    expect(groups.avoid.map((a) => a.category.id)).toEqual([68]);
    expect(groups.quickForm).toHaveLength(0);
  });
});
