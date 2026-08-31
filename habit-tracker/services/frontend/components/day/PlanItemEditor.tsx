'use client';
// [review:need-review] PHASE-03/110, PHASE-03/140
// summary: one plan line edited where it is drawn — text, window and criterion in three fields, save and delete beside them, the arrows that move the line inside its level, and the warning of the canon printed on the line rather than in a modal nobody reads; #140 adds the two optional pickers that turn a line into an intent to act — роль и вид акта, right where the day is already being edited

import { useState } from 'react';
import { ArrowDown, ArrowUp, Check, Trash2, X } from 'lucide-react';
import type { PlanItem, PlanItemPatch, Role } from '@/lib/api';
import {
  ACT_KIND_FIELD_LABEL,
  NO_ACT_KIND_LABEL,
  NO_ROLE_LABEL,
  NO_VALUE,
  ROLE_FIELD_LABEL,
  selectValue,
  selectedId,
  selectedKind,
} from '@/lib/plan-roles';
import { ACT_KIND_OPTIONS } from '@/lib/role-format';
import { clockRange } from '@/lib/time';

/** What the button says before a person is sure. Two taps, not a modal. */
export const DELETE_LABEL = 'Удалить';
export const DELETE_CONFIRM_LABEL = 'Точно удалить';
export const SAVE_LABEL = 'Сохранить';
export const CANCEL_LABEL = 'Отменить';
export const UP_LABEL = 'Выше';
export const DOWN_LABEL = 'Ниже';

export interface PlanItemEditorProps {
  item: PlanItem;
  /** True while a request for this line is in flight; the fields lock. */
  saving: boolean;
  onSave: (patch: PlanItemPatch) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onCancel: () => void;
  /** No place above / below inside this level; the arrow goes flat. */
  atTop: boolean;
  atBottom: boolean;
  /**
   * Справочник ролей для двух необязательных полей (#140).
   *
   * Пустой список — не ошибка, а «справочник не приехал»: полей тогда просто
   * нет, и редактор остаётся ровно тем, чем был до этого тикета.
   */
  roles?: Role[];
}

/**
 * The window of an item as the field shows it: `"ЧЧ:ММ-ЧЧ:ММ"`, or empty.
 *
 * Built from the stored moments in the browser's own zone, because that is the
 * zone the page is being read in and the one the server resolves back against.
 * The day boundary never enters: a window is a pair of wall-clock times, and
 * which day they belong to was decided when the plan was written.
 */
export function windowField(item: PlanItem): string {
  if (!item.starts_at || !item.ends_at) return '';
  return clockRange(item.starts_at, item.ends_at);
}

/**
 * Only what actually changed, so the server is never told to keep what it has.
 *
 * A patch carrying every field would make "not sent" impossible to express, and
 * with it the difference between "не трогай критерий" and "убери критерий" —
 * which is the difference between a corrected word and a task that stops being
 * a task.
 */
export function changedFields(
  item: PlanItem,
  draft: {
    text: string;
    window: string;
    criterion: string;
    roleId?: number | null;
    actKind?: string | null;
  }
): PlanItemPatch {
  const patch: PlanItemPatch = {};
  if (draft.roleId !== undefined && draft.roleId !== item.role_id) {
    patch.role_id = draft.roleId;
  }
  if (draft.actKind !== undefined && draft.actKind !== item.act_kind) {
    patch.act_kind = draft.actKind;
  }
  if (draft.text !== item.text_md) patch.text_md = draft.text;
  const currentWindow = windowField(item);
  if (draft.window !== currentWindow) {
    patch.window = draft.window.trim() === '' ? null : draft.window.trim();
  }
  const currentCriterion = item.done_criterion ?? '';
  if (draft.criterion !== currentCriterion) {
    patch.done_criterion =
      draft.criterion.trim() === '' ? null : draft.criterion.trim();
  }
  return patch;
}

/**
 * The editor of one line, opened in place of the line it edits.
 *
 * In place rather than in a dialogue: the plan is read as a whole — a window
 * next to the window above it, a criterion next to the task it belongs to — and
 * a modal takes exactly that away at the moment it is needed most.
 */
export default function PlanItemEditor({
  item,
  saving,
  onSave,
  onDelete,
  onMoveUp,
  onMoveDown,
  onCancel,
  atTop,
  atBottom,
  roles,
}: PlanItemEditorProps) {
  const [text, setText] = useState(item.text_md);
  const [window, setWindow] = useState(() => windowField(item));
  const [criterion, setCriterion] = useState(item.done_criterion ?? '');
  const [roleId, setRoleId] = useState<number | null>(item.role_id);
  const [actKind, setActKind] = useState<string | null>(item.act_kind);
  const [confirming, setConfirming] = useState(false);

  // Правка соседа переставляет строки, и сервер возвращает уже другой пункт под
  // тем же экраном; поля обязаны последовать за ним, иначе человек сохранит
  // поверх чужого текста то, что набирал в своём. Сброс идёт прямо в рендере, а
  // не эффектом: эффект сначала показал бы кадр со старыми полями и только
  // потом перерисовал его новыми.
  const [shown, setShown] = useState(item);
  if (shown !== item) {
    setShown(item);
    setText(item.text_md);
    setWindow(windowField(item));
    setCriterion(item.done_criterion ?? '');
    setRoleId(item.role_id);
    setActKind(item.act_kind);
    setConfirming(false);
  }

  const field =
    'w-full rounded-2xl bg-surface border border-white/10 px-3 py-2 text-sm text-text-primary';

  return (
    <div className="mt-2 space-y-2" data-testid={`plan-editor-${item.id}`}>
      <label className="block">
        <span className="text-xs text-text-disabled">Текст</span>
        <textarea
          className={field}
          value={text}
          disabled={saving}
          rows={2}
          onChange={(event) => setText(event.target.value)}
          aria-label="Текст пункта"
        />
      </label>

      <div className="flex flex-wrap gap-2">
        <label className="flex-1 min-w-[8rem]">
          <span className="text-xs text-text-disabled">Окно</span>
          <input
            className={field}
            value={window}
            disabled={saving}
            placeholder="09:00-10:30"
            onChange={(event) => setWindow(event.target.value)}
            aria-label="Окно пункта"
          />
        </label>
        <label className="flex-[2] min-w-[12rem]">
          <span className="text-xs text-text-disabled">Сделано</span>
          <input
            className={field}
            value={criterion}
            disabled={saving}
            onChange={(event) => setCriterion(event.target.value)}
            aria-label="Критерий «Сделано»"
          />
        </label>
      </div>

      {roles && roles.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <label className="flex-1 min-w-[8rem]">
            <span className="text-xs text-text-disabled">{ROLE_FIELD_LABEL}</span>
            <select
              className={field}
              value={selectValue(roleId)}
              disabled={saving}
              onChange={(event) => setRoleId(selectedId(event.target.value))}
              aria-label={ROLE_FIELD_LABEL}
            >
              <option value={NO_VALUE}>{NO_ROLE_LABEL}</option>
              {roles.map((role) => (
                <option key={role.id} value={role.id}>
                  {role.title}
                </option>
              ))}
            </select>
          </label>
          <label className="flex-1 min-w-[8rem]">
            <span className="text-xs text-text-disabled">{ACT_KIND_FIELD_LABEL}</span>
            <select
              className={field}
              value={actKind ?? NO_VALUE}
              disabled={saving}
              onChange={(event) => setActKind(selectedKind(event.target.value))}
              aria-label={ACT_KIND_FIELD_LABEL}
            >
              <option value={NO_VALUE}>{NO_ACT_KIND_LABEL}</option>
              {ACT_KIND_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={saving}
          onClick={() =>
            onSave(changedFields(item, { text, window, criterion, roleId, actKind }))
          }
          className="inline-flex items-center gap-1 rounded-2xl bg-lime px-3 py-1.5 text-sm text-black disabled:opacity-50"
        >
          <Check className="w-4 h-4" strokeWidth={2} />
          {SAVE_LABEL}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={onCancel}
          className="inline-flex items-center gap-1 rounded-2xl bg-surface px-3 py-1.5 text-sm text-text-secondary"
        >
          <X className="w-4 h-4" strokeWidth={2} />
          {CANCEL_LABEL}
        </button>

        <button
          type="button"
          disabled={saving || atTop}
          onClick={onMoveUp}
          aria-label={UP_LABEL}
          className="rounded-2xl bg-surface p-1.5 text-text-secondary disabled:opacity-30"
        >
          <ArrowUp className="w-4 h-4" strokeWidth={2} />
        </button>
        <button
          type="button"
          disabled={saving || atBottom}
          onClick={onMoveDown}
          aria-label={DOWN_LABEL}
          className="rounded-2xl bg-surface p-1.5 text-text-secondary disabled:opacity-30"
        >
          <ArrowDown className="w-4 h-4" strokeWidth={2} />
        </button>

        <button
          type="button"
          disabled={saving}
          onClick={() => (confirming ? onDelete() : setConfirming(true))}
          className="ml-auto inline-flex items-center gap-1 rounded-2xl bg-surface px-3 py-1.5 text-sm text-warning"
        >
          <Trash2 className="w-4 h-4" strokeWidth={2} />
          {confirming ? DELETE_CONFIRM_LABEL : DELETE_LABEL}
        </button>
      </div>
    </div>
  );
}
