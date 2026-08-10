'use client';
// [review:need-review] PHASE-01/45-mobile-table-sticky-date, PHASE-01/73-category-field-reorder
// summary: Table-screen state extracted from app/table/page.tsx so the desktop page and /m/table share the same data load, dynamic column building (checklist categories expand to one column per boolean field), tab grouping and optimistic checklist toggle

import { useCallback, useEffect, useState } from 'react';
import {
  categoriesAPI,
  entriesAPI,
  tableAPI,
  type Category,
  type Field,
  type TableCategoryMeta,
  type TableDay,
  type TableResponse,
} from '@/lib/api';
import { toISODate } from '@/lib/date';
import { orderedFields } from '@/lib/today-categories';
import { useRefreshOnVisible } from '@/hooks/useRefreshOnVisible';

/** How many days of history the table spans. */
export const DAYS_SHOWN = 14;

/** Tab name for categories with no group. */
const UNGROUPED_TAB = 'Other';

/** Aggregated cell value marking a checklist field as done / not done. */
export const TRUE_VALUE = 'true';
const FALSE_VALUE = 'false';

function dateRange(): { from: string; to: string } {
  const to = new Date();
  const from = new Date();
  from.setDate(to.getDate() - (DAYS_SHOWN - 1));
  return { from: toISODate(from), to: toISODate(to) };
}

/** One table column: a form category's primary field, or a checklist boolean field. */
export type TableColumn =
  | { kind: 'value'; category: TableCategoryMeta; fieldId: number }
  | { kind: 'check'; category: TableCategoryMeta; fieldId: number; fieldName: string };

/** Stable React key / lookup key for a column. */
export function columnKey(column: TableColumn): string {
  return `${column.category.id}:${column.fieldId}`;
}

function checklistBooleanFields(
  category: TableCategoryMeta,
  fieldsByCategory: Map<number, Field[]>
): Field[] {
  return orderedFields(fieldsByCategory.get(category.id) ?? []).filter(
    (f) => f.field_type === 'boolean'
  );
}

/**
 * Columns grouped into tabs (null group -> Other): checklist categories expand
 * into one column per boolean field, form categories keep their primary field.
 */
function buildTabs(
  categories: TableCategoryMeta[],
  fieldsByCategory: Map<number, Field[]>
): Map<string, TableColumn[]> {
  const tabs = new Map<string, TableColumn[]>();
  const push = (groupKey: string | null, columns: TableColumn[]) => {
    if (columns.length === 0) return;
    const key = groupKey ?? UNGROUPED_TAB;
    tabs.set(key, [...(tabs.get(key) ?? []), ...columns]);
  };
  const named = categories.filter((c) => c.group !== null);
  const ungrouped = categories.filter((c) => c.group === null);
  for (const category of [...named, ...ungrouped]) {
    if (category.display_mode === 'checklist') {
      push(
        category.group,
        checklistBooleanFields(category, fieldsByCategory).map((field) => ({
          kind: 'check' as const,
          category,
          fieldId: field.id,
          fieldName: field.name,
        }))
      );
    } else if (category.primary_field_id !== null) {
      push(category.group, [
        { kind: 'value', category, fieldId: category.primary_field_id },
      ]);
    }
  }
  return tabs;
}

/** Everything a Table screen needs; the two shells differ only in markup. */
export interface UseTableResult {
  loading: boolean;
  error: string | null;
  setError: (message: string | null) => void;
  /** Full category list, for the entry editor's category picker. */
  categories: Category[];
  /** Names of the group tabs, in display order. */
  tabNames: string[];
  /** The tab currently rendered, or null when there are no columns at all. */
  currentTab: string | null;
  setActiveTab: (name: string) => void;
  /** Columns of the current tab. */
  columns: TableColumn[];
  /** Days newest-first, the order both tables render rows in. */
  days: TableDay[];
  /** Aggregated value of one cell, or null when the day has no entry for it. */
  cellValue: (date: string, categoryId: number, fieldId: number) => string | null;
  /** Toggle a checklist cell on any day (backfill), optimistic with rollback. */
  handleToggle: (categoryId: number, fieldId: number, date: string) => Promise<void>;
  /** Re-fetch the table, e.g. after an entry was created or edited. */
  reload: () => Promise<void>;
}

export function useTable(): UseTableResult {
  const [data, setData] = useState<TableResponse | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [fieldsByCategory, setFieldsByCategory] = useState<Map<number, Field[]>>(
    new Map()
  );
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const { from, to } = dateRange();
      const [response, categoriesData] = await Promise.all([
        tableAPI.get(from, to),
        categoriesAPI.getAll(),
      ]);
      setData(response);
      setCategories(categoriesData);
      setFieldsByCategory(
        new Map(categoriesData.map((c: Category) => [c.id, c.fields]))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load table');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Installed as a PWA the page is never reloaded: after adding an entry on
  // /today the table would keep showing the snapshot taken on mount.
  useRefreshOnVisible(loadData);

  const cellValue = useCallback(
    (date: string, categoryId: number, fieldId: number): string | null => {
      const day = data?.days.find((d) => d.date === date);
      const cell = day?.cells.find(
        (c) => c.category_id === categoryId && c.field_id === fieldId
      );
      return cell?.aggregated_value ?? null;
    },
    [data]
  );

  /** Local (optimistic) write of one cell's aggregated value. */
  const setCellChecked = useCallback(
    (categoryId: number, fieldId: number, date: string, checked: boolean) => {
      const value = checked ? TRUE_VALUE : FALSE_VALUE;
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          days: prev.days.map((day) => {
            if (day.date !== date) return day;
            const exists = day.cells.some(
              (c) => c.category_id === categoryId && c.field_id === fieldId
            );
            return {
              ...day,
              cells: exists
                ? day.cells.map((c) =>
                    c.category_id === categoryId && c.field_id === fieldId
                      ? { ...c, aggregated_value: value }
                      : c
                  )
                : [
                    ...day.cells,
                    {
                      category_id: categoryId,
                      field_id: fieldId,
                      aggregated_value: value,
                      entry_count: 1,
                    },
                  ],
            };
          }),
        };
      });
    },
    []
  );

  const handleToggle = useCallback(
    async (categoryId: number, fieldId: number, date: string) => {
      const current = cellValue(date, categoryId, fieldId) === TRUE_VALUE;
      const next = !current;
      setCellChecked(categoryId, fieldId, date, next);
      try {
        await entriesAPI.upsertChecklist({
          category_id: categoryId,
          entry_date: date,
          values: { [fieldId]: next },
        });
      } catch (err) {
        setCellChecked(categoryId, fieldId, date, current);
        setError(err instanceof Error ? err.message : 'Failed to save check');
      }
    },
    [cellValue, setCellChecked]
  );

  const reload = useCallback(async () => {
    await loadData();
  }, [loadData]);

  const tabs = data
    ? buildTabs(data.categories, fieldsByCategory)
    : new Map<string, TableColumn[]>();
  const tabNames = [...tabs.keys()];
  const currentTab =
    activeTab !== null && tabs.has(activeTab) ? activeTab : tabNames[0] ?? null;
  const columns = currentTab !== null ? tabs.get(currentTab) ?? [] : [];
  const days = data ? [...data.days].reverse() : [];

  return {
    loading,
    error,
    setError,
    categories,
    tabNames,
    currentTab,
    setActiveTab,
    columns,
    days,
    cellValue,
    handleToggle,
    reload,
  };
}
