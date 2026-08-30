'use client';
// [review:need-review] PHASE-03/122
// summary: the one keydown listener of Today — mounted by the desktop screen alone, so a key marks nothing on any other route and nothing at all in the mobile shell, which has no keyboard

import { useEffect } from 'react';
import type { QuickMark } from '@/lib/api';
import { resolveHotkey } from '@/lib/quick-mark-hotkeys';

export interface QuickMarkHotkeysOptions {
  /** The directory as the server ordered it; position is what hands out digits. */
  marks: QuickMark[];
  /** True while a modal is up — it owns the keyboard until it closes. */
  dialogOpen: boolean;
  /** Record one mark. The hook resolves the key to an id and knows nothing else. */
  onMark: (quickMarkId: number) => void;
  /** Show the legend. */
  onLegend: () => void;
}

/**
 * Make the keyboard mark things on the screen that called this.
 *
 * The listener lives on `document` and exists only while the component holding
 * it is mounted, which is the whole of "the keys work on Today and nowhere
 * else": no route flag is consulted, because the hook is called from one page.
 * The mobile shell never calls it — a phone has no keyboard, and its buttons
 * keep working by tap.
 *
 * A keystroke that resolves to something is consumed with `preventDefault`, so
 * `?` does not reach the browser's own quick-find. One that resolves to nothing
 * is left alone entirely: typing must stay typing.
 */
export function useQuickMarkHotkeys({
  marks,
  dialogOpen,
  onMark,
  onLegend,
}: QuickMarkHotkeysOptions): void {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const action = resolveHotkey(event, { marks, dialogOpen });
      if (action.kind === 'none') return;
      event.preventDefault();
      if (action.kind === 'legend') {
        onLegend();
        return;
      }
      onMark(action.quickMarkId);
    };

    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [marks, dialogOpen, onMark, onLegend]);
}
