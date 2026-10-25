'use client';
// [review:need-review] PHASE-03/200
// summary: the three fields that link a plan line to a category — the category, its field (taken when there is one candidate, asked for when there are several), and an optional target on a number or a duration — controlled by the line's editor

import type { Category } from '@/lib/api';
import {
  defaultLinkField,
  draftTakesTarget,
  linkableCategories,
  linkableFields,
  type LinkDraft,
} from '@/lib/plan-facts';

export const CATEGORY_FIELD_LABEL = 'Категория';
export const FIELD_FIELD_LABEL = 'Поле для факта';
export const TARGET_FIELD_LABEL = 'Цель';
export const NO_CATEGORY_LABEL = 'Без категории';
export const NO_FIELD_LABEL = '— выберите поле —';
export const CHOOSE_FIELD_HINT =
  'У категории несколько полей — выберите, в какое писать факт';

/** The value an empty `<select>` reports; spelled once for both selects. */
const EMPTY = '';

export interface PlanItemLinkPickerProps {
  categories: Category[];
  draft: LinkDraft;
  disabled: boolean;
  className: string;
  onChange: (draft: LinkDraft) => void;
}

/**
 * Category, field and target of one line, chosen where the line is edited.
 *
 * A new category takes its field only when that field is unambiguous; when two
 * could hold the fact the field stays empty and the editor waits — guessing by
 * name would write 120 повторений into «Подходы».
 */
export default function PlanItemLinkPicker({
  categories,
  draft,
  disabled,
  className,
  onChange,
}: PlanItemLinkPickerProps) {
  const choices = linkableCategories(categories);
  const chosen = choices.find((category) => category.id === draft.categoryId) ?? null;
  const fields = chosen ? linkableFields(chosen) : [];
  const takesTarget = draftTakesTarget(draft, categories);
  const isDuration =
    fields.find((field) => field.id === draft.fieldId)?.field_type === 'duration';

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-2">
        <label className="flex-1 min-w-[8rem]">
          <span className="text-xs text-text-disabled">{CATEGORY_FIELD_LABEL}</span>
          <select
            className={className}
            value={draft.categoryId === null ? EMPTY : String(draft.categoryId)}
            disabled={disabled}
            aria-label={CATEGORY_FIELD_LABEL}
            onChange={(event) => {
              const next =
                choices.find((category) => String(category.id) === event.target.value) ??
                null;
              onChange({
                categoryId: next?.id ?? null,
                fieldId: next ? defaultLinkField(next) : null,
                target: '',
              });
            }}
          >
            <option value={EMPTY}>{NO_CATEGORY_LABEL}</option>
            {choices.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>

        {chosen && (
          <label className="flex-1 min-w-[8rem]">
            <span className="text-xs text-text-disabled">{FIELD_FIELD_LABEL}</span>
            <select
              className={className}
              value={draft.fieldId === null ? EMPTY : String(draft.fieldId)}
              disabled={disabled}
              aria-label={FIELD_FIELD_LABEL}
              onChange={(event) =>
                onChange({
                  ...draft,
                  fieldId: event.target.value === EMPTY ? null : Number(event.target.value),
                  target: '',
                })
              }
            >
              <option value={EMPTY}>{NO_FIELD_LABEL}</option>
              {fields.map((field) => (
                <option key={field.id} value={field.id}>
                  {field.unit ? `${field.name}, ${field.unit}` : field.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {takesTarget && (
          <label className="w-28">
            <span className="text-xs text-text-disabled">{TARGET_FIELD_LABEL}</span>
            <input
              className={className}
              value={draft.target}
              disabled={disabled}
              inputMode={isDuration ? 'text' : 'decimal'}
              placeholder={isDuration ? '1:00' : '300'}
              aria-label={TARGET_FIELD_LABEL}
              onChange={(event) => onChange({ ...draft, target: event.target.value })}
            />
          </label>
        )}
      </div>
      {chosen && draft.fieldId === null && (
        <p className="text-xs text-warning">{CHOOSE_FIELD_HINT}</p>
      )}
    </div>
  );
}
