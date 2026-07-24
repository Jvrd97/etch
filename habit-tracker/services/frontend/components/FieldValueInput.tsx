'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet
// summary: type-aware input for a single entry field value (plus the duration editor behind it), extracted from EntryCard so the mobile shell no longer imports from the desktop card

import { useState } from 'react';
import type { Field } from '@/lib/api';
import { formatSecondsToHM, parseDurationToSeconds, secondsToInputValue } from '@/lib/duration';
import { entryInputClass } from '@/lib/ui-constants';

interface FieldValueInputProps {
  field: Field;
  value: string;
  onChange: (value: string) => void;
  /** DOM id, so a caller's `<label htmlFor>` can name the control. */
  id?: string;
}

/** Type-aware input for a single field value; shared by create and edit forms. */
export function FieldValueInput({ field, value, onChange, id }: FieldValueInputProps) {
  if (field.field_type === 'select') {
    return (
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={field.is_required}
        className={entryInputClass}
      >
        <option value="">Select...</option>
        {field.options?.split(',').map((opt) => (
          <option key={opt} value={opt.trim()}>
            {opt.trim()}
          </option>
        ))}
      </select>
    );
  }
  if (field.field_type === 'boolean') {
    return (
      <input
        id={id}
        type="checkbox"
        checked={value === 'true'}
        onChange={(e) => onChange(e.target.checked.toString())}
        className="w-5 h-5 accent-[#B8FF36] rounded"
      />
    );
  }
  if (field.field_type === 'duration') {
    return (
      <DurationInput
        id={id}
        value={value}
        required={field.is_required}
        onChange={onChange}
      />
    );
  }
  const inputType =
    field.field_type === 'number'
      ? 'number'
      : field.field_type === 'date'
        ? 'date'
        : field.field_type === 'time'
          ? 'time'
          : 'text';
  return (
    <input
      id={id}
      type={inputType}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      required={field.is_required}
      step={field.field_type === 'number' ? 'any' : undefined}
      className={entryInputClass}
    />
  );
}

interface DurationInputProps {
  value: string;
  required?: boolean;
  onChange: (value: string) => void;
  id?: string;
}

/**
 * Duration editor. The stored value is whole seconds (EAV text), but the user
 * types "H:MM" (or bare minutes). Keeps a local text buffer so partial typing
 * is not clobbered; only propagates a value once it parses, and shows a live
 * "1h 20m" hint. Empty input clears the stored value.
 */
export function DurationInput({ value, required, onChange, id }: DurationInputProps) {
  const [text, setText] = useState(() =>
    value === '' ? '' : secondsToInputValue(Number(value))
  );

  const handleChange = (next: string) => {
    setText(next);
    if (next.trim() === '') {
      onChange('');
      return;
    }
    const seconds = parseDurationToSeconds(next);
    if (seconds !== null) onChange(String(seconds));
  };

  const seconds = parseDurationToSeconds(text);

  return (
    <div>
      <input
        id={id}
        type="text"
        inputMode="numeric"
        value={text}
        onChange={(e) => handleChange(e.target.value)}
        required={required}
        placeholder="ч:мм (напр. 1:20)"
        aria-label="Duration (hours:minutes)"
        className={entryInputClass}
      />
      {seconds !== null && seconds > 0 && (
        <span className="mt-1 block text-xs text-text-disabled">
          {formatSecondsToHM(seconds)}
        </span>
      )}
    </div>
  );
}
