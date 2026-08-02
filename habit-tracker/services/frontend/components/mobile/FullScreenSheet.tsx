'use client';
// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/49-device-acceptance-checklist, PHASE-01/84-voice-day-input
// summary: full-screen editor sheet of the mobile shell — Cancel / title / confirm bar (its label and availability overridable, for a sheet whose confirm is not "Done") pinned above a single scrolling content column sized to the visual viewport, an in-sheet error banner, and the modal contract its role promises: Escape, initial focus, focus trap, frozen page behind

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
   * What the confirming action is called here, when "Done" is not what it does.
   *
   * The editors this sheet was built for all end the same way — the form is
   * filled in and committed — but the day-dictation sheet moves through two
   * steps under one bar button, and a bar reading "Done" over a screen whose
   * next step is parsing a retelling is simply the wrong promise.
   */
  doneLabel?: string;
  /**
   * Whether the confirming action is unavailable, separately from `busy`.
   *
   * `busy` already disables Done, but it also relabels it as saving, which is a
   * lie about a step that has not started. A sheet whose first step needs text
   * before it can do anything needs the disabling without the label.
   */
  doneDisabled?: boolean;
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

/**
 * Suppresses the focus change a press on a bar action would cause, keeping the
 * on-screen keyboard open until the click has been delivered.
 *
 * The button still activates: only the default focus move is cancelled, and
 * `click` follows the press regardless.
 */
function keepFocusInField(event: React.MouseEvent) {
  event.preventDefault();
}

function focusablesIn(scope: Element | null): HTMLElement[] {
  if (!scope) return [];
  return Array.from(scope.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

/**
 * The mobile instance's editor chrome: a sheet that owns the whole viewport,
 * with the bar above and the form below.
 *
 * Three decisions carry the keyboard behaviour, and all three are asserted by
 * the tests rather than left to CSS folklore. `100dvh` sizes the sheet before
 * any script runs; from then on it follows `visualViewport`, because iOS keeps
 * the layout viewport at full height under an open keyboard and scrolls the
 * page inside it. The bar sits outside the scrolling region — the flex column
 * scrolls its content only — so a long form cannot carry Cancel or Done off
 * screen. And pressing either action does not move focus, so the keyboard does
 * not close underneath the finger before the click lands.
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
  doneLabel = DONE_LABEL,
  doneDisabled = false,
  error = null,
  onDismissError,
  children,
}: FullScreenSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    // Disabling Done covers the click; this covers Enter (and "Go" on a mobile
    // keyboard), which submits the form without touching the button.
    if (busy || doneDisabled) return;
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

  // `100dvh` is the right size only while no keyboard is open. iOS does not
  // shrink the layout viewport for the keyboard: it shrinks the visual viewport
  // and scrolls the page inside it, which slides the bar — Cancel and Done —
  // above the top edge of the screen with no way to scroll it back. Tracking
  // `visualViewport` pins the sheet to the part of the screen that is actually
  // visible, so the bar stays put whether the keyboard is up or down.
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;

    const follow = () => {
      const sheet = sheetRef.current;
      if (!sheet) return;
      sheet.style.height = `${viewport.height}px`;
      sheet.style.top = `${viewport.offsetTop}px`;
      // `inset-0` also pins the bottom; with an explicit height the two
      // disagree, and the browser is free to resolve that either way.
      sheet.style.bottom = 'auto';
    };

    follow();
    viewport.addEventListener('resize', follow);
    viewport.addEventListener('scroll', follow);
    return () => {
      viewport.removeEventListener('resize', follow);
      viewport.removeEventListener('scroll', follow);
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
            // Tapping a bar action must not move focus out of the field first:
            // that closes the keyboard, the layout reflows under the finger and
            // the click never lands on the button the user aimed at.
            onMouseDown={keepFocusInField}
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
            disabled={busy || doneDisabled}
            onMouseDown={keepFocusInField}
            style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
            className="px-2 text-[15px] font-semibold text-lime transition-opacity duration-200 disabled:opacity-50"
          >
            {busy ? DONE_BUSY_LABEL : doneLabel}
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
