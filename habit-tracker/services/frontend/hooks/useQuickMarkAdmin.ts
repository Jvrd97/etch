'use client';
// [review:need-review] PHASE-03/125
// summary: state of the directory editor — the whole list including switched-off buttons, the categories a button can point at, the conflict of a hotkey kept as data so the form survives it, and the order moved a step at a time rather than by writing numbers

import { useCallback, useEffect, useState } from 'react';
import {
  categoriesAPI,
  quickMarksAPI,
  type Category,
  type HotkeyTaken,
  type QuickMark,
  type QuickMarkDraft,
} from '@/lib/api';

/** What the reader sees when a write failed for a reason nobody phrased. */
export const SAVE_FAILED = 'Сохранить не удалось.';

export interface UseQuickMarkAdminResult {
  /** The whole directory, switched-off buttons included, in its own order. */
  marks: QuickMark[];
  /** Categories a button can point at, with their fields. */
  categories: Category[];
  loading: boolean;
  /** Why the last write failed, in words, or null. */
  error: string | null;
  /** The taken key and its holder, when that is why the last write failed. */
  conflict: HotkeyTaken | null;
  create: (draft: QuickMarkDraft) => Promise<boolean>;
  update: (id: number, draft: QuickMarkDraft) => Promise<boolean>;
  remove: (id: number) => Promise<boolean>;
  /** Move one button one place up or down; the server renumbers the list. */
  move: (id: number, delta: number) => Promise<boolean>;
  /** Forget the last failure — the reader has read it. */
  dismiss: () => void;
  reload: () => void;
}

/**
 * The quick-mark directory as its editor sees it.
 *
 * Read with `activeOnly: false`, unlike Today: a switched-off button is exactly
 * what the editor exists to switch back on, and a list that hides it would make
 * that impossible without SQL.
 *
 * A hotkey conflict is kept as data rather than raised as a message. The repair
 * is "take the key off that other button", and the person has to be able to
 * read which one that is while the form he filled in is still on screen —
 * which is the whole reason the server answers with the holder's id and label.
 */
export function useQuickMarkAdmin(): UseQuickMarkAdminResult {
  const [marks, setMarks] = useState<QuickMark[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<HotkeyTaken | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [directory, catalogue] = await Promise.all([
          quickMarksAPI.list({ activeOnly: false }),
          categoriesAPI.getAll(),
        ]);
        if (cancelled) return;
        setMarks(directory);
        setCategories(catalogue);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : SAVE_FAILED);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const run = useCallback(
    async (call: () => Promise<QuickMark[] | void>): Promise<boolean> => {
      setError(null);
      setConflict(null);
      try {
        const answer = await call();
        if (Array.isArray(answer)) {
          setMarks(answer);
        } else {
          // Правка одной кнопки не говорит, что стало с порядком остальных, —
          // справочник перечитывается целиком, а не склеивается на экране.
          setMarks(await quickMarksAPI.list({ activeOnly: false }));
        }
        return true;
      } catch (err) {
        const taken = hotkeyConflict(err);
        if (taken !== null) setConflict(taken);
        setError(err instanceof Error ? err.message : SAVE_FAILED);
        return false;
      }
    },
    []
  );

  const create = useCallback(
    (draft: QuickMarkDraft) =>
      run(async () => {
        await quickMarksAPI.create(draft);
      }),
    [run]
  );

  const update = useCallback(
    (id: number, draft: QuickMarkDraft) =>
      run(async () => {
        await quickMarksAPI.update(id, draft);
      }),
    [run]
  );

  const remove = useCallback(
    (id: number) =>
      run(async () => {
        await quickMarksAPI.remove(id);
      }),
    [run]
  );

  const move = useCallback(
    (id: number, delta: number) =>
      run(async () => {
        const order = marks.map((mark) => mark.id);
        const from = order.indexOf(id);
        const to = from + delta;
        if (from < 0 || to < 0 || to >= order.length) return marks;
        order.splice(to, 0, ...order.splice(from, 1));
        return await quickMarksAPI.reorder(order);
      }),
    [marks, run]
  );

  const dismiss = useCallback(() => {
    setError(null);
    setConflict(null);
  }, []);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);

  return {
    marks,
    categories,
    loading,
    error,
    conflict,
    create,
    update,
    remove,
    move,
    dismiss,
    reload,
  };
}

/**
 * The taken-key answer inside a failed request, or null.
 *
 * Read off `APIError.detail` rather than parsed out of the message: the server
 * answers with an object precisely so the screen can point at the holder, and
 * pulling an id back out of a sentence would undo that.
 */
export function hotkeyConflict(error: unknown): HotkeyTaken | null {
  if (!(error instanceof Error)) return null;
  const detail = (error as { detail?: unknown }).detail;
  if (
    typeof detail === 'object' &&
    detail !== null &&
    (detail as { error?: unknown }).error === 'hotkey_taken'
  ) {
    return detail as HotkeyTaken;
  }
  return null;
}
