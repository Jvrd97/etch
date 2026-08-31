// [review:need-review] PHASE-03/140
// summary: component tests of the plan's role markup — the item form offers роль and вид акта only when the directory arrived, a change of either travels in the patch and nothing else does, a line carrying both prints what its tick will close, a line carrying one of the two prints nothing, and an act on `/roles` that came from the plan names the line it came from

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import PlanItemEditor, { changedFields } from '@/components/day/PlanItemEditor';
import PlanSections from '@/components/day/PlanSections';
import type { PlanItem, PlanItemPatch, PlanSection, Role, RoleAct } from '@/lib/api';
import {
  ACT_KIND_FIELD_LABEL,
  NO_ROLE_LABEL,
  ROLE_FIELD_LABEL,
  actIntentLine,
  fromPlanLine,
} from '@/lib/plan-roles';

const NONE = new Set<string>();

const ROLES: Role[] = [
  {
    id: 2,
    code: 'architect',
    title: 'Архитектор',
    description: null,
    target_share_pct: 20,
    is_work: true,
    ord: 2,
    is_active: true,
  },
  {
    id: 3,
    code: 'techlead',
    title: 'Тимлид',
    description: null,
    target_share_pct: 50,
    is_work: true,
    ord: 3,
    is_active: true,
  },
];

function item(overrides: Partial<PlanItem> = {}): PlanItem {
  return {
    id: 'item-1',
    parent_id: null,
    ord: 0,
    kind: 'task',
    rigidity: 'soft',
    text_md: 'Архитектурное решение по модели данных',
    text_plain: 'Архитектурное решение по модели данных',
    starts_at: null,
    ends_at: null,
    window_comment: null,
    code: 'W1',
    done_criterion: 'решение записано',
    why_md: null,
    plan_md: null,
    external_ref: null,
    extra: {},
    quarter_goal_id: 1,
    unlinked_reason: null,
    role_id: null,
    act_kind: null,
    carried_from_item_id: null,
    carry_count: 0,
    children: [],
    ...overrides,
  };
}

function section(items: PlanItem[]): PlanSection {
  return {
    id: 'section-1',
    ord: 0,
    title: 'Работа',
    kind: 'work',
    role_id: null,
    items,
  };
}

function act(overrides: Partial<RoleAct> = {}): RoleAct {
  return {
    id: 1,
    work_day: '2026-08-30',
    role_id: 2,
    role_code: 'architect',
    act_kind: 'data_model_decision',
    title: 'Архитектурное решение по модели данных',
    source: 'plan',
    external_ref: 'item-1',
    confidence: 'auto',
    occurred_at: null,
    note: null,
    is_manual: false,
    plan_item_id: 'item-1',
    plan_item_text: 'Архитектурное решение по модели данных',
    ...overrides,
  };
}

function editorFor(line: PlanItem, roles: Role[] | undefined) {
  const onSave = mock((_: PlanItemPatch) => undefined);
  render(
    <PlanItemEditor
      item={line}
      saving={false}
      onSave={onSave}
      onDelete={() => undefined}
      onMoveUp={() => undefined}
      onMoveDown={() => undefined}
      onCancel={() => undefined}
      atTop
      atBottom
      roles={roles}
    />
  );
  return onSave;
}

afterEach(() => {
  cleanup();
});

describe('форма пункта', () => {
  it('предлагает роль и вид акта, когда справочник приехал', () => {
    editorFor(item(), ROLES);
    expect(screen.getByLabelText(ROLE_FIELD_LABEL)).toBeTruthy();
    expect(screen.getByLabelText(ACT_KIND_FIELD_LABEL)).toBeTruthy();
    // «Без роли» — первый вариант: планировать акт заранее не обязанность.
    expect(screen.getByText(NO_ROLE_LABEL)).toBeTruthy();
  });

  it('без справочника остаётся тем же редактором, что до тикета', () => {
    editorFor(item(), undefined);
    expect(screen.queryByLabelText(ROLE_FIELD_LABEL)).toBeNull();
    expect(screen.queryByLabelText(ACT_KIND_FIELD_LABEL)).toBeNull();
  });

  it('везёт в патче только то, что человек поменял', () => {
    const onSave = editorFor(item(), ROLES);
    fireEvent.change(screen.getByLabelText(ROLE_FIELD_LABEL), {
      target: { value: '2' },
    });
    fireEvent.change(screen.getByLabelText(ACT_KIND_FIELD_LABEL), {
      target: { value: 'data_model_decision' },
    });
    fireEvent.click(screen.getByText('Сохранить'));
    expect(onSave).toHaveBeenCalledWith({
      role_id: 2,
      act_kind: 'data_model_decision',
    });
  });

  it('пустой выбор снимает роль, а не оставляет её', () => {
    const line = item({ role_id: 2, act_kind: 'data_model_decision' });
    const onSave = editorFor(line, ROLES);
    fireEvent.change(screen.getByLabelText(ROLE_FIELD_LABEL), {
      target: { value: '' },
    });
    fireEvent.click(screen.getByText('Сохранить'));
    expect(onSave).toHaveBeenCalledWith({ role_id: null });
  });

  it('нетронутые поля роли в патч не попадают', () => {
    const line = item({ role_id: 2, act_kind: 'data_model_decision' });
    const patch = changedFields(line, {
      text: line.text_md,
      window: '',
      criterion: line.done_criterion ?? '',
      roleId: line.role_id,
      actKind: line.act_kind,
    });
    expect(patch).toEqual({});
  });
});

describe('подпись на строке плана', () => {
  it('называет роль и вид акта, когда пункт несёт оба', () => {
    const line = item({ role_id: 2, act_kind: 'data_model_decision' });
    expect(actIntentLine(line, ROLES)).toBe('Архитектор · решение по модели данных');
  });

  it('молчит, когда пункт несёт только половину', () => {
    expect(actIntentLine(item({ role_id: 2 }), ROLES)).toBeNull();
    expect(actIntentLine(item({ act_kind: 'code_review' }), ROLES)).toBeNull();
  });

  it('называет id роли, которой нет в справочнике, вместо пустоты', () => {
    const line = item({ role_id: 99, act_kind: 'code_review' });
    expect(actIntentLine(line, ROLES)).toBe('роль 99 · code review');
  });

  it('печатается на пункте плана', () => {
    const line = item({ role_id: 2, act_kind: 'data_model_decision' });
    render(
      <PlanSections sections={[section([line])]} overlapping={NONE} roles={ROLES} />
    );
    expect(screen.getByText('Архитектор · решение по модели данных')).toBeTruthy();
  });

  it('не печатается на обычном пункте', () => {
    render(
      <PlanSections sections={[section([item()])]} overlapping={NONE} roles={ROLES} />
    );
    expect(screen.queryByText(/·/)).toBeNull();
  });
});

describe('акт на экране ролей', () => {
  it('раскрывается до пункта плана, из которого пришёл', () => {
    expect(fromPlanLine(act())).toBe(
      'из плана: Архитектурное решение по модели данных'
    );
  });

  it('у акта, введённого руками, источника нет', () => {
    expect(
      fromPlanLine(act({ source: 'manual', plan_item_id: null, plan_item_text: null }))
    ).toBeNull();
  });
});
