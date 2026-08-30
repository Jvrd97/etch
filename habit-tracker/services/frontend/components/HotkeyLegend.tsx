'use client';
// [review:need-review] PHASE-03/122
// summary: the "key to button" sheet shown by "?" — every quick mark listed with the key it answers to, a keyless one listed honestly without one, closed by Escape, by the backdrop or by its own button

import { useEffect } from 'react';
import { X } from 'lucide-react';
import type { QuickMark } from '@/lib/api';
import { hotkeyLegendRows } from '@/lib/quick-mark-hotkeys';

interface HotkeyLegendProps {
  /** The directory as it is drawn on screen — same order, same keys. */
  marks: QuickMark[];
  onClose: () => void;
}

/** Shown where a button has no key at all, instead of an empty cell. */
const NO_KEY_LABEL = 'без клавиши';

/**
 * The legend of the quick-mark keys.
 *
 * An invisible shortcut cannot be learned, and the key printed on a button is
 * only readable once the button is on screen. This is the list that answers
 * "what can I press" in one place — built from the same assignment table the
 * keydown handler resolves through, so it cannot describe keys that do nothing.
 *
 * Escape is handled here rather than by the Today listener: while this is up,
 * that listener is deliberately silent, and a dialog that ignores Escape is a
 * trap.
 */
export default function HotkeyLegend({ marks, onClose }: HotkeyLegendProps) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const rows = hotkeyLegendRows(marks);

  return (
    <div
      className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Клавиши быстрых отметок"
        // The sheet itself is not the backdrop: a click inside it must not be
        // read as a click meaning "close".
        onClick={(event) => event.stopPropagation()}
        className="bg-card border border-white/10 rounded-3xl max-w-md w-full max-h-[80vh] overflow-y-auto animate-fade-rise"
      >
        <div className="sticky top-0 bg-card border-b border-white/5 px-6 py-5 flex justify-between items-center rounded-t-3xl">
          <h2 className="text-[22px] font-semibold text-text-primary">Клавиши</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="p-2 rounded-full text-text-secondary hover:text-text-primary hover:bg-white/5 transition-colors duration-200"
          >
            <X className="w-5 h-5" strokeWidth={2} />
          </button>
        </div>

        <ul className="p-6 space-y-2">
          {rows.map((row) => (
            <li key={row.quickMarkId} className="flex items-center gap-3">
              {row.key === null ? (
                <span className="w-8 text-center text-xs text-text-disabled" title={NO_KEY_LABEL}>
                  —
                </span>
              ) : (
                <kbd className="w-8 text-center px-2 py-1 rounded-lg bg-surface border border-white/10 text-xs font-medium text-lime tabular-nums">
                  {row.key}
                </kbd>
              )}
              <span className="text-sm text-text-primary">{row.label}</span>
            </li>
          ))}
        </ul>

        <p className="px-6 pb-6 text-xs text-text-secondary">
          Клавиши работают только на этом экране и молчат, пока курсор стоит в поле ввода. Esc —
          закрыть.
        </p>
      </div>
    </div>
  );
}
