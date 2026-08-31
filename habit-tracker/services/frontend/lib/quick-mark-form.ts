// [review:need-review] PHASE-03/125
// summary: pure form logic of the quick-mark editor — the draft a button is read into and written back from, the fields of the chosen category a chosen kind is allowed to point at, and the same refusals the server makes, phrased before the request is sent

import type { Category, Field, QuickMark, QuickMarkDraft, QuickMarkKind } from '@/lib/api';

/**
 * The editor's own state: every control is a string, including the numbers.
 *
 * A `<input type="number">` hands back `''` while it is being typed into, and a
 * draft that stored `number | null` would have to decide what an empty box
 * means on every keystroke. It means "ничего не введено", which is a string,
 * and it becomes a number once — in `draftToPayload`.
 */
export interface QuickMarkFormDraft {
  label: string;
  categoryId: string;
  fieldId: string;
  kind: QuickMarkKind;
  step: string;
  unitLabel: string;
  icon: string;
  color: string;
  hotkey: string;
  showInAgent: boolean;
  isActive: boolean;
}

/** What the button does, in the words the picker shows. */
export const KIND_LABELS: Record<QuickMarkKind, string> = {
  increment: 'Прибавить шаг',
  check: 'Галка',
  set_value: 'Записать значение',
  relapse: 'Срыв',
};

/** Kinds that write a number, and therefore need a step and a numeric field. */
export const NUMERIC_KINDS: readonly QuickMarkKind[] = ['increment', 'set_value'];

/** Field types a number-writing button can point at. */
export const NUMERIC_FIELD_TYPES: readonly Field['field_type'][] = ['number', 'duration'];

/** A hotkey is one character: the row of buttons is pressed, not typed into. */
export const HOTKEY_MAX_LENGTH = 1;

export const EMPTY_LABEL_ERROR = 'У кнопки должна быть подпись.';
export const NO_CATEGORY_ERROR = 'Выберите категорию.';
export const NO_FIELD_ERROR = 'Выберите поле категории.';
export const STEP_REQUIRED_ERROR =
  'Кнопка, которая пишет число, обязана знать шаг: один тап должен чего-то стоить.';
export const STEP_NOT_A_NUMBER_ERROR = 'Шаг — число.';
export const FIELD_NOT_NUMERIC_ERROR =
  'Это поле не числовое — прибавлять и записывать значение в него нечего.';
export const FIELD_NOT_BOOLEAN_ERROR = 'Галке нужен флажок, а не числовое поле.';
export const RELAPSE_NEEDS_AVOID_ERROR =
  'Срыв ставится только на категорию «избегать».';
export const FIELD_NOT_IN_CATEGORY_ERROR = 'Поле принадлежит другой категории.';

/** A blank form: an increment button, on nothing yet, visible everywhere. */
export function emptyDraft(): QuickMarkFormDraft {
  return {
    label: '',
    categoryId: '',
    fieldId: '',
    kind: 'increment',
    step: '',
    unitLabel: '',
    icon: '',
    color: '',
    hotkey: '',
    showInAgent: true,
    isActive: true,
  };
}

/** An existing button read into the form. */
export function draftFromMark(mark: QuickMark): QuickMarkFormDraft {
  return {
    label: mark.label,
    categoryId: String(mark.category_id),
    fieldId: String(mark.field_id),
    kind: mark.kind,
    step: mark.step === null ? '' : String(mark.step),
    unitLabel: mark.unit_label ?? '',
    icon: mark.icon ?? '',
    color: mark.color ?? '',
    hotkey: mark.hotkey ?? '',
    showInAgent: mark.show_in_agent,
    isActive: mark.is_active,
  };
}

/** An empty box as the API spells "нет значения". */
function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}

/**
 * The form as the request body.
 *
 * Every field is always sent, `null` included: the editor shows the whole
 * button, so a box the person emptied means "снять", and leaving it out of the
 * patch would silently keep the old value on screen and in the database.
 */
export function draftToPayload(draft: QuickMarkFormDraft): QuickMarkDraft {
  const numeric = NUMERIC_KINDS.includes(draft.kind);
  return {
    label: draft.label.trim(),
    category_id: Number(draft.categoryId),
    field_id: Number(draft.fieldId),
    kind: draft.kind,
    step: numeric && draft.step.trim() !== '' ? Number(draft.step) : null,
    unit_label: orNull(draft.unitLabel),
    icon: orNull(draft.icon),
    color: orNull(draft.color),
    hotkey: orNull(draft.hotkey),
    show_in_agent: draft.showInAgent,
    is_active: draft.isActive,
  };
}

/** The chosen category, or null while nothing is chosen. */
export function chosenCategory(
  draft: QuickMarkFormDraft,
  categories: Category[]
): Category | null {
  const id = Number(draft.categoryId);
  if (!Number.isFinite(id) || draft.categoryId === '') return null;
  return categories.find((category) => category.id === id) ?? null;
}

/**
 * The fields the picker is allowed to offer.
 *
 * Filtered by the kind rather than listing the whole category: the pair
 * "kind + field type" is one statement, and a picker that offers a text field
 * to an increment button is a picker whose every second choice is a 422.
 */
export function compatibleFields(category: Category | null, kind: QuickMarkKind): Field[] {
  if (category === null) return [];
  if (NUMERIC_KINDS.includes(kind)) {
    return category.fields.filter((field) => NUMERIC_FIELD_TYPES.includes(field.field_type));
  }
  if (kind === 'check') {
    return category.fields.filter((field) => field.field_type === 'boolean');
  }
  // `relapse` считает сорванные дни: числом на числовом поле, галкой на флажке.
  return category.fields.filter(
    (field) =>
      NUMERIC_FIELD_TYPES.includes(field.field_type) || field.field_type === 'boolean'
  );
}

/**
 * Every reason the form will not be accepted, in the same order the server
 * checks them.
 *
 * Duplicated from `crud/quick_mark.validate_quick_mark` on purpose, and only
 * the part that can be decided from what the screen already has: the категории
 * with their fields are on the client, so a wrong pair does not need a round
 * trip to be refused. The server keeps its own copy — the browser is not the
 * place where the directory's rules live.
 */
export function validateDraft(
  draft: QuickMarkFormDraft,
  categories: Category[]
): string[] {
  const errors: string[] = [];
  if (draft.label.trim() === '') errors.push(EMPTY_LABEL_ERROR);

  const category = chosenCategory(draft, categories);
  if (category === null) {
    errors.push(NO_CATEGORY_ERROR);
  } else if (draft.kind === 'relapse' && category.streak_mode !== 'avoid') {
    errors.push(RELAPSE_NEEDS_AVOID_ERROR);
  }

  const fieldId = Number(draft.fieldId);
  const field =
    category === null || draft.fieldId === ''
      ? null
      : (category.fields.find((one) => one.id === fieldId) ?? null);

  if (draft.fieldId === '') {
    errors.push(NO_FIELD_ERROR);
  } else if (category !== null && field === null) {
    errors.push(FIELD_NOT_IN_CATEGORY_ERROR);
  } else if (field !== null) {
    if (NUMERIC_KINDS.includes(draft.kind) && !NUMERIC_FIELD_TYPES.includes(field.field_type)) {
      errors.push(FIELD_NOT_NUMERIC_ERROR);
    }
    if (draft.kind === 'check' && field.field_type !== 'boolean') {
      errors.push(FIELD_NOT_BOOLEAN_ERROR);
    }
  }

  if (NUMERIC_KINDS.includes(draft.kind)) {
    if (draft.step.trim() === '') {
      errors.push(STEP_REQUIRED_ERROR);
    } else if (!Number.isFinite(Number(draft.step))) {
      errors.push(STEP_NOT_A_NUMBER_ERROR);
    }
  }

  return errors;
}
