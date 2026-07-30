'use client';
// [review:need-review] PHASE-01/63-today-card-tap-and-visibility
// summary: Categories-screen state extracted from app/categories/page.tsx — the list with its layout preference and delete, plus useCategoryDraft, the single owner of the category editor form and of the diff-syncing save both shells post

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  categoriesAPI,
  type Category,
  type CategoryCreate,
  type CategoryDisplayMode,
  type CategoryStreakMode,
  type FieldCreate,
} from '@/lib/api';
import { DEFAULT_CATEGORY_COLOR } from '@/lib/ui-constants';

/**
 * Cards-vs-list layout of the Categories screen.
 *
 * A per-screen preference, unrelated to the desktop/mobile shell `ViewMode` in
 * `lib/view-mode` — the two used to be told apart only by the storage key.
 */
export type CategoryLayout = 'cards' | 'list';

export const CATEGORY_LAYOUT_STORAGE_KEY = 'habit-tracker:categories-layout';

/**
 * Re-exported so the Categories screens keep taking their colour default from
 * the hook they already import; the value itself belongs to `lib/ui-constants`
 * alongside the other cross-shell UI constants.
 */
export { DEFAULT_CATEGORY_COLOR };

export const LOAD_CATEGORIES_ERROR = 'Failed to load categories';
export const DELETE_CATEGORY_ERROR = 'Failed to delete category';
export const SAVE_CATEGORY_ERROR = 'Failed to save category';

/** Everything a Categories list screen needs; the two shells differ only in markup. */
export interface UseCategoriesResult {
  categories: Category[];
  loading: boolean;
  error: string | null;
  setError: (message: string | null) => void;
  /** Cards or list; persisted, so the choice survives a reload. */
  layout: CategoryLayout;
  setLayout: (layout: CategoryLayout) => void;
  reload: () => Promise<void>;
  /** Delete a category and refetch; a rejection lands in `error` and keeps the list. */
  remove: (id: number) => Promise<void>;
}

function readStoredLayout(): CategoryLayout | null {
  if (typeof window === 'undefined') return null;
  const stored = window.localStorage.getItem(CATEGORY_LAYOUT_STORAGE_KEY);
  return stored === 'cards' || stored === 'list' ? stored : null;
}

export function useCategories(): UseCategoriesResult {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [layout, setLayoutState] = useState<CategoryLayout>('cards');

  /**
   * The management screen edits inactive categories too, so it asks for the
   * unfiltered list rather than the active-only default every other screen uses.
   */
  const load = useCallback(async ({ showSpinner = false } = {}) => {
    try {
      if (showSpinner) setLoading(true);
      // Cleared up front rather than on success only: a banner that outlives the
      // failure it reports keeps claiming the screen is broken while the user is
      // already looking at freshly loaded categories.
      setError(null);
      setCategories(await categoriesAPI.getAll(false));
    } catch (err) {
      setError(err instanceof Error ? err.message : LOAD_CATEGORIES_ERROR);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load({ showSpinner: true });
  }, [load]);

  // Read after mount rather than as the initial state: localStorage does not
  // exist while the page is prerendered, and a value read during render would
  // make the server and the client disagree on the first paint.
  useEffect(() => {
    const stored = readStoredLayout();
    if (stored) setLayoutState(stored);
  }, []);

  const setLayout = useCallback((next: CategoryLayout) => {
    setLayoutState(next);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(CATEGORY_LAYOUT_STORAGE_KEY, next);
    }
  }, []);

  const reload = useCallback(async () => {
    await load();
  }, [load]);

  const remove = useCallback(
    async (id: number) => {
      try {
        await categoriesAPI.delete(id);
      } catch (err) {
        setError(err instanceof Error ? err.message : DELETE_CATEGORY_ERROR);
        return;
      }
      await load();
    },
    [load]
  );

  return { categories, loading, error, setError, layout, setLayout, reload, remove };
}

export interface UseCategoryDraftOptions {
  /** Category being edited; null starts a new one. Read once, on mount. */
  category: Category | null;
  /** Called after the category has been persisted. */
  onSaved: () => void;
}

export interface UseCategoryDraftResult {
  name: string;
  setName: (name: string) => void;
  description: string;
  setDescription: (description: string) => void;
  color: string;
  setColor: (color: string) => void;
  displayMode: CategoryDisplayMode;
  setDisplayMode: (mode: CategoryDisplayMode) => void;
  streakMode: CategoryStreakMode;
  setStreakMode: (mode: CategoryStreakMode) => void;
  group: string;
  setGroup: (group: string) => void;
  /**
   * Whether the category shows on Today: `null` leaves it to the heuristic,
   * `true`/`false` is the user overriding it. Tri-state rather than a boolean
   * so a new category does not have to be switched on by hand.
   */
  showInToday: boolean | null;
  setShowInToday: (showInToday: boolean | null) => void;
  isActive: boolean;
  setIsActive: (isActive: boolean) => void;
  /** The draft's fields in display order; existing ones keep their id. */
  fields: FieldCreate[];
  addField: () => void;
  removeField: (index: number) => void;
  updateField: (index: number, updates: Partial<FieldCreate>) => void;
  /** True when a checklist category has no boolean field — the save would be rejected. */
  checklistNeedsBoolean: boolean;
  /** True while the save request is in flight. */
  saving: boolean;
  error: string | null;
  dismissError: () => void;
  /** Persist the draft: update when editing, create otherwise. */
  save: () => Promise<void>;
}

/** A brand-new category starts on one blank field, so there is nothing to add first. */
function blankField(order: number): FieldCreate {
  return { name: '', field_type: 'text', is_required: false, order };
}

/**
 * The category editor's state and its save, so the desktop modal and the mobile
 * sheet differ only in markup.
 *
 * The one non-obvious rule lives in `save`: an existing field is sent back with
 * its `id`, which is what makes the backend update it in place. Drop the id and
 * the field is replaced — the rename goes through, and every value ever logged
 * against the old field is orphaned.
 */
export function useCategoryDraft({
  category,
  onSaved,
}: UseCategoryDraftOptions): UseCategoryDraftResult {
  // Snapshotted on mount: the draft is the user's copy and must not be
  // overwritten by a background reload of the list underneath. Give the editor
  // a `key` tied to the category if it has to be retargeted.
  const [editing] = useState<Category | null>(category);
  const [name, setName] = useState(editing?.name ?? '');
  const [description, setDescription] = useState(editing?.description ?? '');
  const [color, setColor] = useState(editing?.color || DEFAULT_CATEGORY_COLOR);
  const [displayMode, setDisplayMode] = useState<CategoryDisplayMode>(
    editing?.display_mode ?? 'form'
  );
  const [streakMode, setStreakMode] = useState<CategoryStreakMode>(
    editing?.streak_mode ?? 'build'
  );
  const [group, setGroup] = useState(editing?.group ?? '');
  // `?? null` collapses the two "no choice yet" shapes — an absent key on a row
  // written before the column existed, and an explicit null — into the one the
  // rest of the editor speaks.
  const [showInToday, setShowInToday] = useState<boolean | null>(
    editing?.show_in_today ?? null
  );
  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  const [fields, setFields] = useState<FieldCreate[]>(() =>
    editing
      ? editing.fields.map((f) => ({
          id: f.id,
          name: f.name,
          field_type: f.field_type,
          is_required: f.is_required,
          options: f.options,
          order: f.order,
        }))
      : [blankField(0)]
  );
  const [saving, setSaving] = useState(false);
  /** Same fact as `saving`, readable synchronously — see the guard in `save`. */
  const savingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const addField = useCallback(() => {
    // Appended rather than prepended: with many fields you should not have to
    // scroll back up to add one more.
    setFields((prev) => [...prev, blankField(prev.length)]);
  }, []);

  const removeField = useCallback((index: number) => {
    setFields((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateField = useCallback((index: number, updates: Partial<FieldCreate>) => {
    setFields((prev) =>
      prev.map((field, i) => (i === index ? { ...field, ...updates } : field))
    );
  }, []);

  const checklistNeedsBoolean = useMemo(
    () => displayMode === 'checklist' && !fields.some((f) => f.field_type === 'boolean'),
    [displayMode, fields]
  );

  const dismissError = useCallback(() => setError(null), []);

  const save = useCallback(async () => {
    // `saving` is state, so it still reads false for a second call made in the
    // same tick as the first — two submits would then post the same draft twice.
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    setError(null);

    const payload: CategoryCreate = {
      name,
      description,
      color,
      display_mode: displayMode,
      streak_mode: streakMode,
      group: group.trim() || null,
      show_in_today: showInToday,
      is_active: isActive,
      // Unnamed rows are the placeholder the editor hands out, not fields the
      // user filled in; `order` is re-derived from position so add and remove
      // leave no gaps behind.
      fields: fields.filter((f) => f.name.trim()).map((f, i) => ({ ...f, order: i })),
    };

    try {
      if (editing) {
        await categoriesAPI.update(editing.id, payload);
      } else {
        await categoriesAPI.create(payload);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : SAVE_CATEGORY_ERROR);
      savingRef.current = false;
      setSaving(false);
      return;
    }
    // Released before handing control over: `onSaved` typically unmounts the
    // editor, and a state update after that lands on a component that is gone.
    savingRef.current = false;
    setSaving(false);
    onSaved();
  }, [
    color,
    description,
    displayMode,
    editing,
    fields,
    group,
    isActive,
    name,
    onSaved,
    showInToday,
    streakMode,
  ]);

  return {
    name,
    setName,
    description,
    setDescription,
    color,
    setColor,
    displayMode,
    setDisplayMode,
    streakMode,
    setStreakMode,
    group,
    setGroup,
    showInToday,
    setShowInToday,
    isActive,
    setIsActive,
    fields,
    addField,
    removeField,
    updateField,
    checklistNeedsBoolean,
    saving,
    error,
    dismissError,
    save,
  };
}
