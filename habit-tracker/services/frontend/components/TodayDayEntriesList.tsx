'use client';
// [review:need-review] PHASE-01/177, #176, PHASE-01/206
// summary: confirmed Today entries show numeric field units and entry-level actions, under a heading when another list sits above them

import type { Category, Entry } from '@/lib/api';
import { formatValue } from '@/lib/format-value';
import { clockTime } from '@/lib/today-entries';

export interface TodayDayEntriesListProps {
  category: Category;
  entries: Entry[];
  deletingId?: number | null;
  /** Names the list when it is not the only one in the sheet; absent, it has no title. */
  heading?: string;
  onEdit: (entry: Entry) => void;
  onDelete: (entry: Entry) => Promise<boolean>;
  onAdd: () => void;
}

function entryValues(category: Category, entry: Entry): string {
  const fields = new Map(category.fields.map((field) => [field.id, field]));
  const values = entry.values.map((value) => {
    const field = fields.get(value.field_id);
    const renderedValue =
      field?.field_type === 'number'
        ? formatValue(value.value, field.unit)
        : value.value;
    return `${field?.name ?? 'Value'} ${renderedValue}`;
  });
  return values.length === 0 ? 'Без значений' : values.join(', ');
}

/**
 * The shared content of the desktop dialog and mobile full-screen sheet.
 *
 * Only entries with a server id reach this component. The caller deliberately
 * filters local negative ids, because they cannot be edited or deleted yet.
 */
export default function TodayDayEntriesList({
  category,
  entries,
  deletingId = null,
  heading,
  onEdit,
  onDelete,
  onAdd,
}: TodayDayEntriesListProps) {
  return (
    <div className="space-y-3">
      {heading && <h3 className="text-sm font-medium text-text-primary">{heading}</h3>}
      {entries.length === 0 ? (
        <p className="text-sm text-text-secondary">За сегодня записей пока нет.</p>
      ) : (
        <ul className="divide-y divide-white/5 border-y border-white/5">
          {entries.map((entry) => (
            <li key={entry.id} className="flex items-center gap-2 py-3">
              <button
                type="button"
                onClick={() => onEdit(entry)}
                aria-label={`Edit entry ${entry.id}`}
                className="flex min-w-0 flex-1 items-center gap-4 text-left"
              >
                <time className="shrink-0 text-sm tabular-nums text-text-secondary">
                  {clockTime(entry.created_at)}
                </time>
                <span className="min-w-0 truncate text-sm text-text-primary">
                  {entryValues(category, entry)}
                </span>
              </button>
              <button
                type="button"
                onClick={() => void onDelete(entry)}
                disabled={deletingId === entry.id}
                aria-label={`Delete entry ${entry.id}`}
                className="shrink-0 rounded-xl px-3 py-2 text-sm text-text-secondary hover:text-text-primary disabled:opacity-50"
              >
                Удалить
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        onClick={onAdd}
        aria-label="Add entry"
        className="w-full rounded-2xl border border-white/10 px-4 py-3 text-sm font-medium text-lime hover:bg-white/5"
      >
        + Добавить запись
      </button>
    </div>
  );
}
