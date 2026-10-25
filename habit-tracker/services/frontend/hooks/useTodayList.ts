'use client';
// [review:need-review] PHASE-01/206
// summary: which day list a Today card has open — the records of a category, or the sets of a quick-mark card beside them — held once for both shells, with the card read live so its counter moves while the list is up

import { useCallback, useState } from 'react';
import type { Category, QuickMark } from '@/lib/api';

/** What the card pressed asked to see; ids, not objects, so the list reads the live ones. */
interface OpenList {
  categoryId: number;
  markId: number | null;
}

export interface TodayList {
  open: boolean;
  /** The category whose records are listed; null when it is not among the active ones. */
  category: Category | null;
  /** The quick-mark card the list was opened from, as it stands now; null for a record card. */
  mark: QuickMark | null;
  /** Name of the sheet or dialog. */
  title: string;
  openCategory: (category: Category) => void;
  openMark: (mark: QuickMark) => void;
  close: () => void;
}

/**
 * The list a Today card opens.
 *
 * One state for two shells: the phone shows it as a full-screen sheet and the
 * desktop as a dialog, but what it contains — and which card it belongs to — is
 * the same question. Only one list can be up at a time.
 *
 * The card is held by id and read from `marks` on every render. A snapshot of
 * it would freeze the counter at the value it had when the list opened, and the
 * point of undoing a set from this list is to watch that counter go down.
 */
export function useTodayList(categories: Category[], marks: QuickMark[]): TodayList {
  const [opened, setOpened] = useState<OpenList | null>(null);

  const openCategory = useCallback(
    (category: Category) => setOpened({ categoryId: category.id, markId: null }),
    []
  );
  const openMark = useCallback(
    (mark: QuickMark) => setOpened({ categoryId: mark.category_id, markId: mark.id }),
    []
  );
  const close = useCallback(() => setOpened(null), []);

  const mark =
    opened?.markId == null ? null : (marks.find((one) => one.id === opened.markId) ?? null);
  const category = opened
    ? (categories.find((one) => one.id === opened.categoryId) ?? null)
    : null;
  // A card that left the directory while its list was up has nothing left to
  // list; the sheet goes with it rather than staying open over a missing card.
  const open = opened !== null && (opened.markId === null || mark !== null);

  return {
    open,
    category,
    mark,
    title: `${category?.name ?? mark?.label ?? ''} — сегодня`,
    openCategory,
    openMark,
    close,
  };
}
