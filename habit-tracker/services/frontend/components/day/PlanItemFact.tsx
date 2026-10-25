'use client';
// [review:need-review] PHASE-03/200
// summary: the fact card under a plan line linked to a category — what the line is linked to with a way into its history, the target kept apart from what was done, an input that fits the field (a number with its unit, a duration as h:mm, a box as one button) plus the other fields of a composite category, «Добавить ещё», the correction and the two-tap delete of what the line wrote, the reason a broken link takes no input, and the notice that an untick left the history in place

import { useState } from 'react';
import { History, Pencil, Plus, Trash2 } from 'lucide-react';
import type {
  FieldType,
  MarkState,
  PlanFactDraft,
  PlanFactEntry,
  PlanFactValueDraft,
  PlanItemFacts,
  PlanLinkField,
  Unmark,
} from '@/lib/api';
import {
  factValueText,
  historyHref,
  isTrueText,
  linkStateText,
  markAfterCorrect,
  markAfterRecord,
  markAfterRemove,
  parseFactInput,
  progressText,
} from '@/lib/plan-facts';
import { secondsToInputValue } from '@/lib/duration';

export const RECORD_LABEL = 'Записать';
export const ADD_MORE_LABEL = 'Добавить ещё';
export const CORRECT_LABEL = 'Исправить';
export const SAVE_CORRECTION_LABEL = 'Сохранить исправление';
export const CANCEL_CORRECTION_LABEL = 'Отмена';
export const DELETE_FACT_LABEL = 'Удалить запись';
export const DELETE_FACT_CONFIRM_LABEL = 'Точно удалить';
export const HISTORY_LABEL = 'История';
export const WAS_THERE_LABEL = 'Было';
export const WAS_NOT_LABEL = 'Не было';
export const UNREADABLE_VALUE = 'Введите число: «300», «3,5» или «1:30» для времени';
export const UNTICKED_NOTICE =
  'Галочка снята, а запись в истории осталась. Исправьте или удалите её, если её не было.';

/** The unit a duration travels in; the card shows h:mm and sends seconds. */
const DURATION_UNIT = 's';

export interface PlanItemFactProps {
  facts: PlanItemFacts;
  /** The line's mark — to notice an untick that left the history behind. */
  markState: MarkState | null;
  saving: boolean;
  error: string | null;
  /** The phone links to its own history screen and trims the type scale. */
  compact?: boolean;
  onRecord: (draft: PlanFactDraft) => void;
  onCorrect: (entryId: number, draft: PlanFactDraft) => void;
  onRemove: (entryId: number, mark: Unmark | null) => void;
}

/** The text an input starts from when an entry is being corrected. */
function inputOf(field: PlanLinkField, entry: PlanFactEntry | null): string {
  const raw = entry?.values.find((one) => one.field_id === field.id)?.value ?? '';
  if (field.field_type === 'duration' && raw !== '') {
    const seconds = Number(raw);
    return Number.isFinite(seconds) ? secondsToInputValue(seconds) : raw;
  }
  return field.field_type === 'boolean' ? '' : raw;
}

/** One typed value as the API takes it; the unit rides along so the server can check it. */
function valueDraft(
  field: PlanLinkField,
  value: number | boolean
): PlanFactValueDraft {
  if (field.field_type === 'duration') {
    return { field_id: field.id, value, unit: DURATION_UNIT };
  }
  if (field.field_type === 'number' && field.unit) {
    return { field_id: field.id, value, unit: field.unit };
  }
  return { field_id: field.id, value };
}

function inputLabel(field: PlanLinkField): string {
  return field.field_type === 'number' && field.unit
    ? `${field.name}, ${field.unit}`
    : field.name;
}

/** A hint that cannot be mistaken for a value already typed. */
function placeholderOf(fieldType: FieldType): string | undefined {
  return fieldType === 'duration' ? 'ч:мм' : undefined;
}

/**
 * The card a linked line carries: what was done, typed where the plan is read.
 *
 * The fact is typed here once and lands in the category history — the person
 * does not open the category to type it again. A tick of the line stays a tick:
 * it says nothing about how many, and this card is the only place a number is
 * entered.
 */
export default function PlanItemFact({
  facts,
  markState,
  saving,
  error,
  compact = false,
  onRecord,
  onCorrect,
  onRemove,
}: PlanItemFactProps) {
  const { link } = facts;
  const main = link.fields.find((field) => field.id === link.field_id) ?? null;
  const others = link.fields.filter((field) => field.id !== link.field_id);

  const [inputs, setInputs] = useState<Record<number, string>>({});
  const [flags, setFlags] = useState<Record<number, boolean>>({});
  const [correcting, setCorrecting] = useState<PlanFactEntry | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [unreadable, setUnreadable] = useState(false);

  // «Снял галочку» is not «этого не было»: the entry stays, and the card says
  // so at the moment the tick goes, rather than deleting anything on its own.
  const [lastMark, setLastMark] = useState(markState);
  const [unticked, setUnticked] = useState(false);
  if (lastMark !== markState) {
    setUnticked(lastMark === 'done' && markState !== 'done' && facts.entries.length > 0);
    setLastMark(markState);
  }

  const brokenText = linkStateText(link.state);
  const field =
    'w-24 rounded-2xl bg-surface border border-white/10 px-3 py-1.5 text-sm text-text-primary';

  const startCorrection = (entry: PlanFactEntry) => {
    setCorrecting(entry);
    setDeleting(null);
    setUnreadable(false);
    const typed: Record<number, string> = {};
    const ticked: Record<number, boolean> = {};
    for (const one of link.fields) {
      typed[one.id] = inputOf(one, entry);
      const raw = entry.values.find((value) => value.field_id === one.id)?.value;
      ticked[one.id] = isTrueText(raw);
    }
    setInputs(typed);
    setFlags(ticked);
  };

  const reset = () => {
    setInputs({});
    setFlags({});
    setCorrecting(null);
    setUnreadable(false);
  };

  /** Every filled field as a value; null when the main one is missing or unreadable. */
  const collect = (mainValue?: boolean): PlanFactValueDraft[] | null => {
    if (main === null) return null;
    const values: PlanFactValueDraft[] = [];
    for (const one of [main, ...others]) {
      if (one.field_type === 'boolean') {
        const flag = one.id === main.id && mainValue !== undefined ? mainValue : flags[one.id];
        if (flag !== undefined && (one.id === main.id || flag)) {
          values.push(valueDraft(one, flag));
        }
        continue;
      }
      const raw = inputs[one.id] ?? '';
      if (raw.trim() === '') {
        if (one.id === main.id) return null;
        continue;
      }
      const parsed = parseFactInput(one.field_type, raw);
      if (parsed === null) return null;
      values.push(valueDraft(one, parsed));
    }
    return values;
  };

  const submit = (mainValue?: boolean) => {
    const values = collect(mainValue);
    if (values === null || values.length === 0) {
      setUnreadable(true);
      return;
    }
    setUnreadable(false);
    const linked = values[0].value;
    const mark = correcting
      ? markAfterCorrect(facts, correcting.entry_id, linked)
      : markAfterRecord(facts, linked);
    const draft: PlanFactDraft = mark === null ? { values } : { values, mark };
    if (correcting) onCorrect(correcting.entry_id, draft);
    else onRecord(draft);
    reset();
  };

  return (
    <div
      className={`mt-2 rounded-2xl bg-surface/60 border border-white/5 space-y-2 text-sm ${
        compact ? 'p-2' : 'p-3'
      }`}
      data-testid={`plan-fact-${facts.item_id}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-text-primary">{link.category_name}</span>
        {link.field_name && (
          <span className="text-text-secondary">· {link.field_name}</span>
        )}
        <a
          href={historyHref(link.category_id, compact)}
          className="inline-flex items-center gap-1 text-text-secondary hover:text-text-primary"
        >
          <History className="w-3.5 h-3.5" strokeWidth={2} />
          {HISTORY_LABEL}
        </a>
      </div>

      <p className={facts.progress === 'partial' ? 'text-warning' : 'text-text-secondary'}>
        {progressText(facts)}
      </p>

      {facts.entries.length > 0 && (
        <ul className="space-y-1">
          {facts.entries.map((entry) => (
            <li key={entry.entry_id} className="flex flex-wrap items-center gap-2">
              <span className="text-text-primary">
                {factValueText(
                  link.field_type,
                  entry.values.find((one) => one.field_id === link.field_id)?.value ?? null,
                  link.unit
                )}
              </span>
              <span className="text-xs text-text-disabled">{entry.entry_date}</span>
              {link.state === 'ok' && (
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => startCorrection(entry)}
                  className="inline-flex items-center gap-1 rounded-2xl px-2 py-0.5 text-xs text-text-secondary"
                >
                  <Pencil className="w-3 h-3" strokeWidth={2} />
                  {CORRECT_LABEL}
                </button>
              )}
              <button
                type="button"
                disabled={saving}
                onClick={() =>
                  deleting === entry.entry_id
                    ? onRemove(entry.entry_id, markAfterRemove(facts, entry.entry_id))
                    : setDeleting(entry.entry_id)
                }
                className="inline-flex items-center gap-1 rounded-2xl px-2 py-0.5 text-xs text-warning"
              >
                <Trash2 className="w-3 h-3" strokeWidth={2} />
                {deleting === entry.entry_id ? DELETE_FACT_CONFIRM_LABEL : DELETE_FACT_LABEL}
              </button>
            </li>
          ))}
        </ul>
      )}

      {unticked && <p className="text-warning">{UNTICKED_NOTICE}</p>}

      {brokenText !== null || main === null ? (
        <p className="text-warning">{brokenText}</p>
      ) : (
        <div className="flex flex-wrap items-end gap-2">
          {main.field_type === 'boolean' ? (
            <>
              {/* A ticked box takes no second «Было»: one more tap would be a
                  second visit in the history. «Исправить» still offers both. */}
              {(correcting || !facts.done) && (
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => submit(true)}
                  className="rounded-2xl bg-lime px-3 py-1.5 text-sm text-black disabled:opacity-50"
                >
                  {WAS_THERE_LABEL}
                </button>
              )}
              {correcting && (
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => submit(false)}
                  className="rounded-2xl bg-surface px-3 py-1.5 text-sm text-text-secondary"
                >
                  {WAS_NOT_LABEL}
                </button>
              )}
            </>
          ) : (
            <FactInput
              field={main}
              value={inputs[main.id] ?? ''}
              disabled={saving}
              className={field}
              onChange={(value) => setInputs((current) => ({ ...current, [main.id]: value }))}
            />
          )}

          {others.map((one) =>
            one.field_type === 'boolean' ? (
              <label key={one.id} className="inline-flex items-center gap-1 text-text-secondary">
                <input
                  type="checkbox"
                  checked={flags[one.id] ?? false}
                  disabled={saving}
                  onChange={(event) =>
                    setFlags((current) => ({ ...current, [one.id]: event.target.checked }))
                  }
                />
                {one.name}
              </label>
            ) : (
              <FactInput
                key={one.id}
                field={one}
                value={inputs[one.id] ?? ''}
                disabled={saving}
                className={field}
                onChange={(value) => setInputs((current) => ({ ...current, [one.id]: value }))}
              />
            )
          )}

          {main.field_type !== 'boolean' && (
            <button
              type="button"
              disabled={saving}
              onClick={() => submit()}
              className="inline-flex items-center gap-1 rounded-2xl bg-lime px-3 py-1.5 text-sm text-black disabled:opacity-50"
            >
              <Plus className="w-4 h-4" strokeWidth={2} />
              {correcting
                ? SAVE_CORRECTION_LABEL
                : facts.entries.length > 0
                  ? ADD_MORE_LABEL
                  : RECORD_LABEL}
            </button>
          )}
          {correcting && (
            <button
              type="button"
              disabled={saving}
              onClick={reset}
              className="rounded-2xl bg-surface px-3 py-1.5 text-sm text-text-secondary"
            >
              {CANCEL_CORRECTION_LABEL}
            </button>
          )}
        </div>
      )}

      {unreadable && <p className="text-warning">{UNREADABLE_VALUE}</p>}
      {error && <p className="text-warning">{error}</p>}
    </div>
  );
}

interface FactInputProps {
  field: PlanLinkField;
  value: string;
  disabled: boolean;
  className: string;
  onChange: (value: string) => void;
}

/** A number as a number keyboard, a duration as h:mm — the field decides which. */
function FactInput({ field, value, disabled, className, onChange }: FactInputProps) {
  const label = inputLabel(field);
  return (
    <label className="inline-flex flex-col">
      <span className="text-xs text-text-disabled">{label}</span>
      <input
        className={className}
        value={value}
        disabled={disabled}
        inputMode={field.field_type === 'duration' ? 'text' : 'decimal'}
        placeholder={placeholderOf(field.field_type)}
        aria-label={label}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
