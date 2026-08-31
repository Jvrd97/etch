// [review:need-review] PHASE-03/110
// summary: component tests for editing one plan line in place — the patch carries only what changed, an emptied field arrives as null rather than as an empty string, deleting asks twice instead of opening a modal, the arrows go flat at the ends of a level, and the plan drawn with a warning shows it on the line the server named

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import PlanItemEditor, {
  CANCEL_LABEL,
  DELETE_CONFIRM_LABEL,
  DELETE_LABEL,
  DOWN_LABEL,
  SAVE_LABEL,
  UP_LABEL,
  changedFields,
  windowField,
} from '@/components/day/PlanItemEditor';
import PlanSections, { EDIT_LINE_LABEL } from '@/components/day/PlanSections';
import type { PlanItem, PlanItemPatch, PlanSection } from '@/lib/api';

const NONE = new Set<string>();

function item(overrides: Partial<PlanItem> = {}): PlanItem {
  return {
    id: 'item-1',
    parent_id: null,
    ord: 0,
    kind: 'task',
    rigidity: 'soft',
    text_md: 'Написать письмо',
    text_plain: 'Написать письмо',
    starts_at: null,
    ends_at: null,
    window_comment: null,
    code: 'W1',
    done_criterion: 'письмо отправлено',
    why_md: null,
    plan_md: null,
    external_ref: null,
    extra: {},
    quarter_goal_id: 1,
    unlinked_reason: null,
    carried_from_item_id: null,
    carry_count: 0,
    children: [],
    ...overrides,
  } as PlanItem;
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

function editorFor(line: PlanItem, props: Record<string, unknown> = {}) {
  const onSave = mock((_: PlanItemPatch) => undefined);
  const onDelete = mock(() => undefined);
  const onMoveUp = mock(() => undefined);
  const onMoveDown = mock(() => undefined);
  render(
    <PlanItemEditor
      item={line}
      saving={false}
      atTop={false}
      atBottom={false}
      onSave={onSave}
      onDelete={onDelete}
      onMoveUp={onMoveUp}
      onMoveDown={onMoveDown}
      onCancel={() => undefined}
      {...props}
    />
  );
  return { onSave, onDelete, onMoveUp, onMoveDown };
}

afterEach(cleanup);

describe('changedFields: only what the person actually changed', () => {
  it('sends nothing when nothing was touched', () => {
    const line = item();
    const patch = changedFields(line, {
      text: line.text_md,
      window: '',
      criterion: line.done_criterion ?? '',
    });

    expect(patch).toEqual({});
  });

  it('sends a cleared criterion as null, not as an empty string', () => {
    // Разница несущая: пустая строка — это критерий из нуля символов, который
    // `CHECK` пропустит, а `null` — снятый критерий, который он и должен
    // отвергнуть. Склеить их значило бы тихо развалить задачу.
    const line = item();

    const patch = changedFields(line, {
      text: line.text_md,
      window: '',
      criterion: '   ',
    });

    expect(patch).toEqual({ done_criterion: null });
  });

  it('sends a typed window as the wall clock the server parses', () => {
    const line = item();

    const patch = changedFields(line, {
      text: line.text_md,
      window: ' 09:00-10:30 ',
      criterion: line.done_criterion ?? '',
    });

    expect(patch).toEqual({ window: '09:00-10:30' });
  });
});

describe('windowField: the window as the field shows it', () => {
  it('is empty for a line that claims no piece of the clock', () => {
    expect(windowField(item())).toBe('');
  });

  it('reads back the stored moments as ЧЧ:ММ-ЧЧ:ММ', () => {
    const start = new Date(2026, 7, 31, 9, 0);
    const end = new Date(2026, 7, 31, 10, 30);

    const field = windowField(
      item({ starts_at: start.toISOString(), ends_at: end.toISOString() })
    );

    expect(field).toBe('09:00-10:30');
  });
});

describe('PlanItemEditor: the controls beside the line', () => {
  it('saves the patch the fields describe', () => {
    const line = item();
    const { onSave } = editorFor(line);

    fireEvent.change(screen.getByLabelText('Текст пункта'), {
      target: { value: 'Написать письмо и отправить' },
    });
    fireEvent.click(screen.getByText(SAVE_LABEL));

    expect(onSave).toHaveBeenCalledWith({ text_md: 'Написать письмо и отправить' });
  });

  it('asks twice before deleting instead of opening a modal', () => {
    // Второе нажатие вместо диалога: подтверждение остаётся на той же строке,
    // и человек видит, что именно удаляет, а не читает «вы уверены?».
    const { onDelete } = editorFor(item());

    fireEvent.click(screen.getByText(DELETE_LABEL));
    expect(onDelete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText(DELETE_CONFIRM_LABEL));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it('flattens the arrow that has nowhere to go', () => {
    editorFor(item(), { atTop: true });

    expect((screen.getByLabelText(UP_LABEL) as HTMLButtonElement).disabled).toBe(
      true
    );
    expect((screen.getByLabelText(DOWN_LABEL) as HTMLButtonElement).disabled).toBe(
      false
    );
  });

  it('locks every field while the edit is in flight', () => {
    editorFor(item(), { saving: true });

    expect(
      (screen.getByLabelText('Текст пункта') as HTMLTextAreaElement).disabled
    ).toBe(true);
    expect(
      (screen.getByText(SAVE_LABEL).closest('button') as HTMLButtonElement).disabled
    ).toBe(true);
    expect(
      (screen.getByText(CANCEL_LABEL).closest('button') as HTMLButtonElement)
        .disabled
    ).toBe(true);
  });
});

describe('PlanSections: the plan as an editor', () => {
  const editing = {
    openId: null,
    saving: null,
    warnings: new Map<string, string>(),
    onOpen: () => undefined,
    onSave: () => undefined,
    onDelete: () => undefined,
    onMove: () => undefined,
    onAdd: () => undefined,
  };

  it('opens the editor on the line whose id is named', () => {
    render(
      <PlanSections
        sections={[section([item()])]}
        overlapping={NONE}
        editing={{ ...editing, openId: 'item-1' }}
      />
    );

    expect(screen.getByTestId('plan-editor-item-1')).toBeTruthy();
  });

  it('shows a pencil on a line nobody is editing yet', () => {
    render(
      <PlanSections sections={[section([item()])]} overlapping={NONE} editing={editing} />
    );

    expect(screen.getByLabelText(EDIT_LINE_LABEL)).toBeTruthy();
    expect(screen.queryByTestId('plan-editor-item-1')).toBeNull();
  });

  it('prints the warning of the canon under the line the server named', () => {
    // Подписью на пункте, а не модальным окном: правка прошла, и прерывать
    // человека нечем — ему надо увидеть, какое правило он только что нарушил.
    render(
      <PlanSections
        sections={[section([item()])]}
        overlapping={NONE}
        editing={{
          ...editing,
          warnings: new Map([['W1', 'в плане 5 рабочих задач, канон разрешает 4']]),
        }}
      />
    );

    expect(
      screen.getByText('в плане 5 рабочих задач, канон разрешает 4')
    ).toBeTruthy();
  });

  it('draws no editing controls at all when the plan is only being read', () => {
    render(<PlanSections sections={[section([item()])]} overlapping={NONE} />);

    expect(screen.queryByLabelText(EDIT_LINE_LABEL)).toBeNull();
  });
});
