// [review:need-review] PHASE-03/nav-drawer
// summary: the keyboard half of the modal contract, shared by every dialog in the app — what the browser considers focusable, and the Tab wrap that keeps focus inside one element

/**
 * Everything the browser would stop at while tabbing through a dialog.
 *
 * Spelled once rather than per dialog: a selector that drifts is a modal whose
 * trap silently lets focus out through the one control its own copy forgot.
 */
export const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** Focusable descendants of `scope`, in document (and therefore tab) order. */
export function focusablesIn(scope: Element | null): HTMLElement[] {
  if (!scope) return [];
  return Array.from(scope.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

/**
 * The part of a Tab keypress this module needs, so the same call works for a
 * React synthetic event and for a listener bound to `document`.
 */
export interface TabKeyEvent {
  shiftKey: boolean;
  preventDefault(): void;
}

/**
 * Wraps Tab around the edges of `scope`, so focus cannot leave an open dialog.
 *
 * Only the two edges and the outside case need handling; in between, the
 * browser's own tab order is already correct. Focus sitting outside `scope` is
 * the case a container-bound handler never sees but a document-bound one does:
 * a click on the dialog's own padding moves focus to `body`, and without this
 * the next Tab would walk into the frozen page behind the dialog.
 */
export function trapTab(event: TabKeyEvent, scope: Element | null): void {
  const focusables = focusablesIn(scope);
  if (focusables.length === 0) return;
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const active = document.activeElement;

  if (active === null || scope === null || !scope.contains(active)) {
    event.preventDefault();
    first.focus();
    return;
  }
  if (event.shiftKey && active === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}
