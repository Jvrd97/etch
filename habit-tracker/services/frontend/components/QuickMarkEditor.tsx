'use client';
// [review:need-review] PHASE-03/125
// summary: the form one quick mark is entered and edited in — category and the compatible fields of it, kind, step, unit, key, the two switches, and the taken-key answer shown beside the key box without emptying anything the person typed

import { useState, type FormEvent } from 'react';
import type { Category, HotkeyTaken } from '@/lib/api';
import {
  KIND_LABELS,
  NUMERIC_KINDS,
  chosenCategory,
  compatibleFields,
  validateDraft,
  type QuickMarkFormDraft,
} from '@/lib/quick-mark-form';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

export const SAVE_LABEL = 'Сохранить';
export const CANCEL_LABEL = 'Отмена';
export const SHOW_IN_AGENT_LABEL = 'Показывать в окне агента';
export const IS_ACTIVE_LABEL = 'Кнопка включена';
export const HOTKEY_LABEL = 'Клавиша';
export const STEP_LABEL = 'Шаг';
export const UNIT_LABEL = 'Единица';
export const LABEL_LABEL = 'Подпись';
export const CATEGORY_LABEL = 'Категория';
export const FIELD_LABEL_TEXT = 'Поле';
export const KIND_LABEL = 'Что делает тап';
export const ICON_LABEL = 'Иконка';
export const COLOR_LABEL = 'Цвет';

/** Said under the switch, because the two words are easy to read as synonyms. */
export const IS_ACTIVE_HINT =
  'Выключенная кнопка уходит с экрана, но остаётся в справочнике вместе с клавишей. ' +
  'Записанные ею значения и события журнала не трогаются.';

/** Said next to the agent switch, because its effect is on a screen elsewhere. */
export const SHOW_IN_AGENT_HINT =
  'В плавающем окне помещается пять-шесть кнопок. Снятая галка убирает кнопку из окна ' +
  'и оставляет её на Today.';

const FIELD_LABEL_CLASS = 'block text-xs uppercase tracking-wide text-text-secondary mb-1';
const INPUT_CLASS =
  'w-full bg-surface border border-white/10 rounded-2xl px-3 py-2 text-sm text-text-primary outline-none focus:border-lime';

export interface QuickMarkEditorProps {
  /** The form state, owned by the screen so a failed save keeps it on screen. */
  draft: QuickMarkFormDraft;
  onChange: (draft: QuickMarkFormDraft) => void;
  categories: Category[];
  /** The taken key and its holder, when the last save was refused for it. */
  conflict: HotkeyTaken | null;
  /** True while editing an existing button, false while entering a new one. */
  editing: boolean;
  onSubmit: () => void;
  onCancel: () => void;
  /** Size controls as touch targets — the mobile shell owes every control 44px. */
  touch?: boolean;
}

/**
 * One button of the directory, as a form.
 *
 * The draft lives in the screen above rather than here, and that is the whole
 * point of the component: a hotkey conflict comes back from the server after
 * the request, and a form that held its own state would either remount and lose
 * what was typed, or keep a second copy of it that the screen cannot show the
 * conflict against.
 *
 * The field picker offers only the fields the chosen kind can write to. The
 * server refuses the rest anyway (`validate_quick_mark`); offering them would
 * make every second choice a 422 the person has to translate back into "возьми
 * другое поле".
 */
export default function QuickMarkEditor({
  draft,
  onChange,
  categories,
  conflict,
  editing,
  onSubmit,
  onCancel,
  touch = false,
}: QuickMarkEditorProps) {
  const [showErrors, setShowErrors] = useState(false);
  const category = chosenCategory(draft, categories);
  const fields = compatibleFields(category, draft.kind);
  const errors = validateDraft(draft, categories);
  const numeric = NUMERIC_KINDS.includes(draft.kind);
  const sizing = touch ? { minHeight: TAP_TARGET_PX } : undefined;

  const set = <K extends keyof QuickMarkFormDraft>(
    key: K,
    value: QuickMarkFormDraft[K]
  ): void => {
    onChange({ ...draft, [key]: value });
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (errors.length > 0) {
      setShowErrors(true);
      return;
    }
    setShowErrors(false);
    onSubmit();
  };

  return (
    <form onSubmit={submit} className="space-y-4" aria-label={editing ? 'Правка кнопки' : 'Новая кнопка'}>
      <div>
        <label className={FIELD_LABEL_CLASS} htmlFor="qm-label">
          {LABEL_LABEL}
        </label>
        <input
          id="qm-label"
          value={draft.label}
          onChange={(event) => set('label', event.target.value)}
          className={INPUT_CLASS}
          style={sizing}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor="qm-kind">
            {KIND_LABEL}
          </label>
          <select
            id="qm-kind"
            value={draft.kind}
            onChange={(event) =>
              // Смена вида меняет список совместимых полей, поэтому выбранное
              // поле снимается: иначе на экране осталась бы пара, которую
              // сервер отвергнет, и человек не увидел бы, что именно не так.
              onChange({
                ...draft,
                kind: event.target.value as QuickMarkFormDraft['kind'],
                fieldId: '',
              })
            }
            className={INPUT_CLASS}
            style={sizing}
          >
            {Object.entries(KIND_LABELS).map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor="qm-category">
            {CATEGORY_LABEL}
          </label>
          <select
            id="qm-category"
            value={draft.categoryId}
            onChange={(event) =>
              onChange({ ...draft, categoryId: event.target.value, fieldId: '' })
            }
            className={INPUT_CLASS}
            style={sizing}
          >
            <option value="">—</option>
            {categories.map((one) => (
              <option key={one.id} value={String(one.id)}>
                {one.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className={FIELD_LABEL_CLASS} htmlFor="qm-field">
          {FIELD_LABEL_TEXT}
        </label>
        <select
          id="qm-field"
          value={draft.fieldId}
          onChange={(event) => set('fieldId', event.target.value)}
          className={INPUT_CLASS}
          style={sizing}
        >
          <option value="">—</option>
          {fields.map((field) => (
            <option key={field.id} value={String(field.id)}>
              {field.name}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {numeric && (
          <div>
            <label className={FIELD_LABEL_CLASS} htmlFor="qm-step">
              {STEP_LABEL}
            </label>
            <input
              id="qm-step"
              inputMode="decimal"
              value={draft.step}
              onChange={(event) => set('step', event.target.value)}
              className={INPUT_CLASS}
              style={sizing}
            />
          </div>
        )}
        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor="qm-unit">
            {UNIT_LABEL}
          </label>
          <input
            id="qm-unit"
            value={draft.unitLabel}
            onChange={(event) => set('unitLabel', event.target.value)}
            className={INPUT_CLASS}
            style={sizing}
          />
        </div>
        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor="qm-hotkey">
            {HOTKEY_LABEL}
          </label>
          <input
            id="qm-hotkey"
            maxLength={1}
            value={draft.hotkey}
            onChange={(event) => set('hotkey', event.target.value)}
            className={INPUT_CLASS}
            style={sizing}
          />
        </div>
      </div>

      {conflict !== null && (
        <p role="alert" className="text-sm text-danger">
          {conflict.message}
        </p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor="qm-icon">
            {ICON_LABEL}
          </label>
          <input
            id="qm-icon"
            value={draft.icon}
            onChange={(event) => set('icon', event.target.value)}
            className={INPUT_CLASS}
            style={sizing}
          />
        </div>
        <div>
          <label className={FIELD_LABEL_CLASS} htmlFor="qm-color">
            {COLOR_LABEL}
          </label>
          <input
            id="qm-color"
            value={draft.color}
            onChange={(event) => set('color', event.target.value)}
            placeholder="#B8FF36"
            className={INPUT_CLASS}
            style={sizing}
          />
        </div>
      </div>

      <div className="space-y-3">
        <label className="flex items-center gap-3 text-sm text-text-primary">
          <input
            type="checkbox"
            checked={draft.showInAgent}
            onChange={(event) => set('showInAgent', event.target.checked)}
          />
          {SHOW_IN_AGENT_LABEL}
        </label>
        <p className="text-xs text-text-secondary">{SHOW_IN_AGENT_HINT}</p>

        <label className="flex items-center gap-3 text-sm text-text-primary">
          <input
            type="checkbox"
            checked={draft.isActive}
            onChange={(event) => set('isActive', event.target.checked)}
          />
          {IS_ACTIVE_LABEL}
        </label>
        <p className="text-xs text-text-secondary">{IS_ACTIVE_HINT}</p>
      </div>

      {showErrors && errors.length > 0 && (
        <ul role="alert" className="text-sm text-danger space-y-1">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}

      <div className="flex gap-3">
        <button
          type="submit"
          className="px-4 py-2 rounded-2xl bg-lime text-black text-sm font-medium"
          style={sizing}
        >
          {SAVE_LABEL}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 rounded-2xl border border-white/10 text-sm text-text-secondary"
          style={sizing}
        >
          {CANCEL_LABEL}
        </button>
      </div>
    </form>
  );
}
