// [review:need-review] PHASE-03/200
// summary: pure helpers of a plan line linked to a category — which field a link defaults to (and when the person must choose instead), reading a typed number or duration, wording a fact, its progress against the target and a broken link, when a write also ticks the line, and the key that makes a retried write the same write

import type {
  Category,
  Field,
  FieldType,
  MarkState,
  PlanItemFacts,
  PlanLinkState,
} from '@/lib/api';
import {
  formatSecondsToHM,
  parseDurationToSeconds,
  secondsToInputValue,
} from '@/lib/duration';

/** The field types a fact can be typed into from the plan. */
export const LINKABLE_FIELD_TYPES: readonly FieldType[] = [
  'number',
  'duration',
  'boolean',
];

/** The field types a target can sit on: «сходить в зал» has no number. */
export const TARGET_FIELD_TYPES: readonly FieldType[] = ['number', 'duration'];

const MARK_DONE: MarkState = 'done';

/** Fields of a category a fact can be typed into, in the category's order. */
export function linkableFields(category: Category): Field[] {
  return category.fields.filter((field) =>
    LINKABLE_FIELD_TYPES.includes(field.field_type)
  );
}

/**
 * The field a new link points at, or null when the person has to choose.
 *
 * The category's own primary field wins; a single candidate is taken as is.
 * Two candidates and no primary is exactly the case the plan must not guess —
 * «Тренировка» with «Подходы» and «Повторения» has no right answer by name.
 */
export function defaultLinkField(category: Category): number | null {
  const candidates = linkableFields(category);
  const primary = candidates.find((field) => field.id === category.primary_field_id);
  if (primary) return primary.id;
  return candidates.length === 1 ? candidates[0].id : null;
}

/**
 * A typed value as the API wants it: a number, or whole seconds; null when unreadable.
 *
 * A comma is a decimal point: on a Russian phone keyboard «3,5» is what 3.5 looks like.
 */
export function parseFactInput(fieldType: FieldType, input: string): number | null {
  if (fieldType === 'duration') return parseDurationToSeconds(input);
  const trimmed = input.trim().replace(',', '.');
  if (trimmed === '') return null;
  const number = Number(trimmed);
  return Number.isFinite(number) ? number : null;
}

/** The spellings a stored box reads as ticked — the backend's `is_true_value`. */
const TRUE_TEXTS: readonly string[] = ['true', '1', 'yes'];

/** Whether a stored box value means «было». */
export function isTrueText(raw: string | null | undefined): boolean {
  return raw !== null && raw !== undefined && TRUE_TEXTS.includes(raw.trim().toLowerCase());
}

/** A stored value worded for the card. */
export function factValueText(
  fieldType: FieldType | null,
  raw: string | null,
  unit: string | null
): string {
  if (raw === null || raw === '') return '—';
  if (fieldType === 'boolean') {
    return isTrueText(raw) ? 'было' : 'не было';
  }
  if (fieldType === 'duration') {
    const seconds = Number(raw);
    return Number.isFinite(seconds) ? formatSecondsToHM(seconds) : raw;
  }
  return unit ? `${raw} ${unit}` : raw;
}

/** A number of the linked field, without its unit. */
function bareAmount(facts: PlanItemFacts, amount: number): string {
  return facts.link.field_type === 'duration'
    ? formatSecondsToHM(amount)
    : String(amount);
}

/** A number of the linked field with its unit, as the card prints it. */
function amountText(facts: PlanItemFacts, amount: number): string {
  const bare = bareAmount(facts, amount);
  return facts.link.unit && facts.link.field_type !== 'duration'
    ? `${bare} ${facts.link.unit}`
    : bare;
}

/**
 * Where the line stands, in one sentence: the target and the fact kept apart.
 *
 * «Сделано 100 из 300» and «Цель 300, пока не записано» are different
 * statements, and the second must never read like the first.
 */
export function progressText(facts: PlanItemFacts): string {
  const target = facts.link.target_value;
  if (facts.progress === 'none') {
    return target === null
      ? 'Пока не записано'
      : `Цель ${amountText(facts, target)}, пока не записано`;
  }
  if (facts.link.field_type === 'boolean') {
    return facts.done ? 'Было' : 'Записано: не было';
  }
  const total = facts.total ?? 0;
  if (target === null) return `Записано ${amountText(facts, total)}`;
  return `Сделано ${bareAmount(facts, total)} из ${amountText(facts, target)}`;
}

/** Why a link cannot take a fact, or null when it can. */
export function linkStateText(state: PlanLinkState): string | null {
  const texts: Record<PlanLinkState, string | null> = {
    ok: null,
    category_missing: 'Категории больше нет — запись из плана невозможна',
    category_archived: 'Категория в архиве — запись из плана невозможна',
    checklist_category: 'Чек-лист ведёт одну запись на день — отмечайте его на Today',
    field_missing: 'Поле удалено из категории — выберите другое поле',
    field_not_in_category: 'Поле не из этой категории — выберите поле заново',
    field_unsupported: 'В это поле из плана не записать — выберите числовое поле',
    target_needs_number: 'Цель стоит на галочке — уберите цель или смените поле',
  };
  return texts[state];
}

/** A total that already includes `value` reaches the target. */
function reaches(facts: PlanItemFacts, total: number): boolean {
  const target = facts.link.target_value;
  return target === null || total >= target;
}

/**
 * The mark a new fact should carry: `done` once the line is done, else none.
 *
 * A partial fact leaves the mark alone — 100 of 300 is recorded as 100 and the
 * line is not declared done for the person.
 */
export function markAfterRecord(
  facts: PlanItemFacts,
  value: number | boolean
): MarkState | null {
  if (typeof value === 'boolean') return value ? MARK_DONE : null;
  return reaches(facts, (facts.total ?? 0) + value) ? MARK_DONE : null;
}

/** The mark after correcting `entryId` to `value`: its old value counted out. */
export function markAfterCorrect(
  facts: PlanItemFacts,
  entryId: number,
  value: number | boolean
): MarkState | null {
  if (typeof value === 'boolean') return value ? MARK_DONE : null;
  const fieldId = facts.link.field_id;
  const entry = facts.entries.find((one) => one.entry_id === entryId);
  const old = Number(entry?.values.find((one) => one.field_id === fieldId)?.value ?? 0);
  const total = (facts.total ?? 0) - (Number.isFinite(old) ? old : 0) + value;
  return reaches(facts, total) ? MARK_DONE : null;
}

/**
 * A key that makes a retried write the same write.
 *
 * Kept by the hook until an answer arrives, so the second press after a lost
 * answer goes under the key of the first. The fallback covers http:// origins
 * where `crypto.randomUUID` is missing; it only has to be unique in this tab.
 */
export function newFactKey(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `fact-${uuid}`;
  return `fact-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** The history screen of a category, on the desktop or on the phone. */
export function historyHref(categoryId: number, compact: boolean): string {
  return compact ? `/m/categories/${categoryId}` : `/categories/${categoryId}`;
}

export const FACT_SAVE_ERROR = 'Факт не сохранился';

/**
 * The sentence a refused write shows: the reasons of a 422, the message of a 409.
 *
 * Read by shape rather than by `instanceof APIError`: a value import from
 * `@/lib/api` here would be one more name every test mock of that module has
 * to carry, and the shape is all this needs.
 */
export function factErrorText(error: unknown): string {
  if (!(error instanceof Error)) return FACT_SAVE_ERROR;
  const detail: unknown = 'detail' in error ? error.detail : null;
  if (typeof detail === 'object' && detail !== null && 'reasons' in detail) {
    const reasons: unknown = detail.reasons;
    if (Array.isArray(reasons) && reasons.length > 0) {
      return `${FACT_SAVE_ERROR}: ${reasons.join('; ')}`;
    }
  }
  return error.message && error.message !== 'An error occurred'
    ? error.message
    : FACT_SAVE_ERROR;
}

/** The link as the editor holds it while the person chooses. */
export interface LinkDraft {
  categoryId: number | null;
  fieldId: number | null;
  /** As typed: a number, or h:mm for a duration; '' for no target. */
  target: string;
}

/** The categories a line may be linked to: active, not a checklist, with a field. */
export function linkableCategories(categories: Category[]): Category[] {
  return categories.filter(
    (category) =>
      category.is_active &&
      category.display_mode !== 'checklist' &&
      linkableFields(category).length > 0
  );
}

/** The link a line already has, as the editor starts from it. */
export function linkDraftOf(
  item: { category_id?: number | null; field_id?: number | null; target_value?: number | null },
  categories: Category[]
): LinkDraft {
  const fieldId = item.field_id ?? null;
  const field = categories
    .find((category) => category.id === item.category_id)
    ?.fields.find((one) => one.id === fieldId);
  const target = item.target_value ?? null;
  return {
    categoryId: item.category_id ?? null,
    fieldId,
    target:
      target === null
        ? ''
        : field?.field_type === 'duration'
          ? secondsToInputValue(target)
          : String(target),
  };
}

/** The field type the draft's field has, or null. */
function draftFieldType(draft: LinkDraft, categories: Category[]): FieldType | null {
  return (
    categories
      .find((category) => category.id === draft.categoryId)
      ?.fields.find((one) => one.id === draft.fieldId)?.field_type ?? null
  );
}

/** Whether a target can sit on the draft's field at all. */
export function draftTakesTarget(draft: LinkDraft, categories: Category[]): boolean {
  const type = draftFieldType(draft, categories);
  return type !== null && TARGET_FIELD_TYPES.includes(type);
}

/**
 * Whether the draft can be saved: no link, or a category with its field chosen.
 *
 * A category without a field is the ambiguous case — the editor waits for the
 * person rather than saving a link the server would refuse.
 */
export function linkDraftReady(draft: LinkDraft, categories: Category[]): boolean {
  if (draft.categoryId === null) return true;
  if (draft.fieldId === null) return false;
  if (draft.target.trim() === '' || !draftTakesTarget(draft, categories)) return true;
  const type = draftFieldType(draft, categories);
  return type !== null && parseFactInput(type, draft.target) !== null;
}

/**
 * The part of a patch the link contributes: nothing when it did not change.
 *
 * Sent as a set — category, field and target together — because the three only
 * mean something together; unlinking sends the category alone, and the server
 * clears the other two with it.
 */
export function linkPatch(
  item: { category_id?: number | null; field_id?: number | null; target_value?: number | null },
  draft: LinkDraft,
  categories: Category[]
): { category_id?: number | null; field_id?: number | null; target_value?: number | null } {
  if (draft.categoryId === null) {
    return (item.category_id ?? null) === null ? {} : { category_id: null };
  }
  const type = draftFieldType(draft, categories);
  const target =
    type !== null && TARGET_FIELD_TYPES.includes(type) && draft.target.trim() !== ''
      ? parseFactInput(type, draft.target)
      : null;
  const same =
    draft.categoryId === (item.category_id ?? null) &&
    draft.fieldId === (item.field_id ?? null) &&
    target === (item.target_value ?? null);
  return same
    ? {}
    : { category_id: draft.categoryId, field_id: draft.fieldId, target_value: target };
}
