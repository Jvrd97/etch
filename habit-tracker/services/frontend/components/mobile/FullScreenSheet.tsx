'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet
// summary: full-screen editor sheet of the mobile shell — Cancel / title / Done bar pinned above a single scrolling content column (sized in dvh so an open keyboard never moves the bar), an in-sheet error banner, and the modal contract its role promises: Escape, initial focus, focus trap, frozen page behind

import { useCallback, useEffect, useRef } from 'react';
import ErrorAlert from '@/components/ErrorAlert';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

export interface FullScreenSheetProps {
  /** Bar title, and the accessible name of the dialog. */
  title: string;
  /** Left bar action: discard and close. Stays enabled while saving. */
  onCancel: () => void;
  /** Right bar action, also fired by submitting the form (Enter in a field). */
  onDone: () => void;
  /** True while the save is in flight: Done is disabled and announces itself. */
  busy?: boolean;
  /**
   * Message of the last failed action, shown at the top of the sheet's content.
   *
   * It belongs here rather than on the page underneath: the sheet covers the
   * whole viewport, so a banner rendered by the screen behind it is invisible
   * and Done appears to do nothing.
   */
  error?: string | null;
  /** Dismiss the banner; without it the banner has no close control. */
  onDismissError?: () => void;
  children: React.ReactNode;
}

/** Label of the confirming bar action, in both of its states. */
const DONE_LABEL = 'Done';
const DONE_BUSY_LABEL = 'Saving...';

/** Everything the browser would stop at while tabbing through the sheet. */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function focusablesIn(scope: Element | null): HTMLElement[] {
  if (!scope) return [];
  return Array.from(scope.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

/**
 * The mobile instance's editor chrome: a sheet that owns the whole viewport,
 * with the bar above and the form below.
 *
 * Two layout decisions carry the keyboard behaviour, and both are asserted by
 * the tests rather than left to CSS folklore. The sheet is sized in `dvh`, so
 * the browser shrinks it to the area the keyboard leaves visible instead of
 * keeping a `vh` box whose bottom is hidden. And the bar sits outside the
 * scrolling region — the flex column scrolls its content only — so scrolling a
 * long form under an open keyboard can never carry Cancel or Done off-screen.
 *
 * `role="dialog" aria-modal="true"` is a promise to assistive tech, and the
 * effects below are what make it true: focus starts in the form, Tab cannot
 * leave the sheet, Escape closes it, and the page behind it does not scroll.
 */
export default function FullScreenSheet({
  title,
  onCancel,
  onDone,
  busy = false,
  error = null,
  onDismissError,
  children,
}: FullScreenSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    // Disabling Done covers the click; this covers Enter (and "Go" on a mobile
    // keyboard), which submits the form without touching the button.
    if (busy) return;
    onDone();
  };

  // Scrolling the list behind an open sheet is the classic mobile modal bug:
  // the sheet stays put while the page underneath drifts, and closing it lands
  // the user somewhere else entirely.
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  // Focus starts on the first field rather than on Cancel: the sheet exists to
  // be filled in, and an editor that opens with the discard action focused
  // invites exactly the keystroke that throws the draft away.
  useEffect(() => {
    const sheet = sheetRef.current;
    if (!sheet) return;
    const content = sheet.querySelector('[data-sheet-scroll]');
    const target = focusablesIn(content)[0] ?? focusablesIn(sheet)[0];
    target?.focus();
  }, []);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusables = focusablesIn(sheetRef.current);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement;

      // Only the two edges need handling; in between, the browser's own tab
      // order is already correct.
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [onCancel]
  );

  return (
    <div
      ref={sheetRef}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onKeyDown={handleKeyDown}
      className="fixed inset-0 z-50 h-[100dvh] bg-background flex flex-col animate-fade-rise"
    >
      <form onSubmit={handleSubmit} className="flex flex-col flex-1 min-h-0">
        <div className="flex items-center gap-2 px-3 border-b border-white/5 bg-background/95 backdrop-blur-md pt-[env(safe-area-inset-top)]">
          <button
            type="button"
            onClick={onCancel}
            style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
            className="px-2 text-[15px] font-medium text-text-secondary transition-colors duration-200 hover:text-text-primary"
          >
            Cancel
          </button>
          <h2 className="flex-1 text-center text-[17px] font-semibold text-text-primary truncate">
            {title}
          </h2>
          <button
            type="submit"
            disabled={busy}
            style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
            className="px-2 text-[15px] font-semibold text-lime transition-opacity duration-200 disabled:opacity-50"
          >
            {busy ? DONE_BUSY_LABEL : DONE_LABEL}
          </button>
        </div>

        <div
          data-sheet-scroll
          className="flex-1 min-h-0 overflow-y-auto px-4 py-4 pb-[calc(env(safe-area-inset-bottom)+1.5rem)] space-y-5"
        >
          {error && <ErrorAlert message={error} onDismiss={onDismissError} />}
          {children}
        </div>
      </form>
    </div>
  );
}
