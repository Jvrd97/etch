// [review:need-review] PHASE-03/200
// summary: component tests for linking a plan line to a category in its editor — one candidate field is taken, two make the person choose before saving, the target travels with the link, unlinking sends the category away alone, and an unlinked line offers «Связать с категорией» right where it is drawn

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import PlanItemEditor, { SAVE_LABEL } from '@/components/day/PlanItemEditor';
import {
  CATEGORY_FIELD_LABEL,
  CHOOSE_FIELD_HINT,
  FIELD_FIELD_LABEL,
  NO_CATEGORY_LABEL,
  TARGET_FIELD_LABEL,
} from '@/components/day/PlanItemLinkPicker';
import PlanSections, { LINK_LINE_LABEL } from '@/components/day/PlanSections';
import type { Category, Field, PlanItem, PlanItemPatch } from '@/lib/api';

afterEach(() => {
  cleanup();
});

function field(id: number, name: string, field_type: Field['field_type'], unit: string | null = null): Field {
  return {
    id,
    category_id: 0,
    name,
    field_type,
    is_required: false,
    order: id,
    unit,
    created_at: '',
    updated_at: '',
  };
}

function category(id: number, name: string, fields: Field[]): Category {
  return {
    id,
    name,
    display_mode: 'form',
    streak_mode: 'build',
    primary_field_id: null,
    is_active: true,
    created_at: '',
    updated_at: '',
    fields,
  };
}

const PUSHUPS = category(5, 'Отжимания', [field(11, 'Повторения', 'number', 'раз')]);
const WORKOUT = category(6, 'Тренировка', [
  field(21, 'Подходы', 'number'),
  field(22, 'Повторения', 'number'),
]);
const CATEGORIES = [PUSHUPS, WORKOUT];

function line(overrides: Partial<PlanItem> = {}): PlanItem {
  return {
    id: 'item-1',
    parent_id: null,
    ord: 0,
    kind: 'bullet',
    rigidity: 'soft',
    text_md: 'Отжимания',
    text_plain: 'Отжимания',
    starts_at: null,
    ends_at: null,
    window_comment: null,
    code: 'P1',
    done_criterion: null,
    why_md: null,
    plan_md: null,
    external_ref: null,
    extra: {},
    quarter_goal_id: null,
    unlinked_reason: null,
    role_id: null,
    act_kind: null,
    carried_from_item_id: null,
    carry_count: 0,
    children: [],
    ...overrides,
  };
}

function editorFor(item: PlanItem, categories: Category[] = CATEGORIES) {
  const saved: PlanItemPatch[] = [];
  render(
    <PlanItemEditor
      item={item}
      saving={false}
      atTop={false}
      atBottom={false}
      onSave={(patch) => saved.push(patch)}
      onDelete={() => undefined}
      onMoveUp={() => undefined}
      onMoveDown={() => undefined}
      onCancel={() => undefined}
      categories={categories}
    />
  );
  return { saved };
}

function choose(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe('linking a line to a category', () => {
  it('takes the only field a fact fits and sends the target with it', () => {
    const { saved } = editorFor(line());

    choose(CATEGORY_FIELD_LABEL, '5');
    choose(TARGET_FIELD_LABEL, '300');
    fireEvent.click(screen.getByText(SAVE_LABEL));

    expect(saved[0]).toEqual({
      category_id: 5,
      field_id: 11,
      target_value: 300,
    });
  });

  it('asks which field when two could hold the fact', () => {
    const { saved } = editorFor(line());

    choose(CATEGORY_FIELD_LABEL, '6');

    expect(screen.getByText(CHOOSE_FIELD_HINT)).toBeDefined();
    expect((screen.getByText(SAVE_LABEL).closest('button') as HTMLButtonElement).disabled).toBe(
      true
    );

    choose(FIELD_FIELD_LABEL, '22');
    fireEvent.click(screen.getByText(SAVE_LABEL));

    expect(saved[0]).toEqual({
      category_id: 6,
      field_id: 22,
      target_value: null,
    });
  });

  it('unlinks with the category alone', () => {
    const { saved } = editorFor(line({ category_id: 5, field_id: 11, target_value: 300 }));

    choose(CATEGORY_FIELD_LABEL, '');
    fireEvent.click(screen.getByText(SAVE_LABEL));

    expect(saved[0]).toEqual({ category_id: null });
  });

  it('edits the text of a line whose category went to the archive without touching its link', () => {
    const { saved } = editorFor(line({ category_id: 9, field_id: 91, target_value: 300 }));

    fireEvent.change(screen.getByLabelText('Текст пункта'), {
      target: { value: 'Отжимания утром' },
    });
    fireEvent.click(screen.getByText(SAVE_LABEL));

    expect(saved[0]).toEqual({ text_md: 'Отжимания утром' });
  });

  it('edits the text of a linked line before the categories have loaded', () => {
    const { saved } = editorFor(line({ category_id: 5, field_id: 11, target_value: 300 }), []);

    fireEvent.change(screen.getByLabelText('Текст пункта'), {
      target: { value: 'Отжимания утром' },
    });
    fireEvent.click(screen.getByText(SAVE_LABEL));

    expect(saved[0]).toEqual({ text_md: 'Отжимания утром' });
  });

  it('shows no picker when there are no categories to pick from', () => {
    editorFor(line(), []);

    expect(screen.queryByLabelText(CATEGORY_FIELD_LABEL)).toBeNull();
  });

  it('names the option that leaves a line unlinked', () => {
    editorFor(line());

    expect(screen.getByText(NO_CATEGORY_LABEL)).toBeDefined();
  });

  it('offers «Связать с категорией» on an unlinked line of an editable plan', () => {
    const opened: Array<string | null> = [];
    render(
      <PlanSections
        sections={[
          { id: 's1', ord: 0, title: 'Вечер', kind: 'evening', role_id: null, items: [line()] },
        ]}
        overlapping={new Set()}
        editing={{
          openId: null,
          saving: null,
          warnings: new Map(),
          onOpen: (id) => opened.push(id),
          onSave: () => undefined,
          onDelete: () => undefined,
          onMove: () => undefined,
          onAdd: () => undefined,
        }}
        facts={{
          byItem: new Map(),
          categories: CATEGORIES,
          saving: new Set(),
          errors: new Map(),
          onRecord: () => undefined,
          onCorrect: () => undefined,
          onRemove: () => undefined,
        }}
      />
    );

    fireEvent.click(screen.getByText(LINK_LINE_LABEL));

    expect(opened).toEqual(['item-1']);
  });
});
