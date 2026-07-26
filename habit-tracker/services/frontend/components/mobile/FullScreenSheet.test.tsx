// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet
// summary: tests for FullScreenSheet — bar actions, submit wiring, busy state, the in-sheet error banner, the modal contract (Escape, initial focus, focus trap, body scroll lock) and the keyboard-safe layout contract

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import FullScreenSheet from './FullScreenSheet';

afterEach(() => {
  cleanup();
  restoreVisualViewport();
});

const originalVisualViewport = Object.getOwnPropertyDescriptor(window, 'visualViewport');

function restoreVisualViewport() {
  if (originalVisualViewport) {
    Object.defineProperty(window, 'visualViewport', originalVisualViewport);
  } else {
    delete (window as unknown as Record<string, unknown>).visualViewport;
  }
}

/**
 * Stands in for `window.visualViewport`, which happy-dom does not implement and
 * no test environment can shrink with a real on-screen keyboard anyway.
 */
function fakeVisualViewport(initial: { height: number; offsetTop: number }) {
  const listeners = new Set<() => void>();
  const viewport = {
    ...initial,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  };
  Object.defineProperty(window, 'visualViewport', { value: viewport, configurable: true });
  return {
    emit(next: { height: number; offsetTop: number }) {
      Object.assign(viewport, next);
      for (const listener of listeners) listener();
    },
    listenerCount: () => listeners.size,
  };
}

function renderSheet(props: Partial<React.ComponentProps<typeof FullScreenSheet>> = {}) {
  const onCancel = props.onCancel ?? mock(() => {});
  const onDone = props.onDone ?? mock(() => {});
  const view = render(
    <FullScreenSheet title="New entry" onCancel={onCancel} onDone={onDone} {...props}>
      <input aria-label="Notes" />
    </FullScreenSheet>
  );
  return { onCancel, onDone, view };
}

describe('FullScreenSheet', () => {
  it('renders as a modal dialog titled by its bar', () => {
    renderSheet();
    const dialog = screen.getByRole('dialog');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(screen.getByText('New entry')).toBeDefined();
  });

  it('cancels through the left bar action', () => {
    const { onCancel } = renderSheet();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('confirms through the right bar action', () => {
    const { onDone } = renderSheet();
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('submits when the user presses Enter in a field', () => {
    const { onDone } = renderSheet();
    fireEvent.submit(screen.getByRole('dialog').querySelector('form')!);
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('blocks a second submit while the first is in flight', () => {
    const { onDone } = renderSheet({ busy: true });
    const done = screen.getByRole('button', { name: 'Saving...' });
    expect((done as HTMLButtonElement).disabled).toBe(true);

    // Disabling the button is not enough: Enter (or "Go" on a mobile keyboard)
    // in a text field submits the form directly, bypassing the button entirely.
    fireEvent.submit(screen.getByRole('dialog').querySelector('form')!);
    expect(onDone).not.toHaveBeenCalled();
  });

  it('keeps Cancel reachable while saving, so a stuck request is escapable', () => {
    const { onCancel } = renderSheet({ busy: true });
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    expect((cancel as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(cancel);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('covers the whole viewport in dynamic units, so the keyboard does not resize the layout', () => {
    renderSheet();
    const dialog = screen.getByRole('dialog');
    expect(dialog.className).toContain('fixed');
    expect(dialog.className).toContain('inset-0');
    // dvh, not vh: with vh the sheet stays taller than the visible area once the
    // on-screen keyboard opens and the bar is pushed off-screen.
    expect(dialog.className).toContain('h-[100dvh]');
  });

  it('follows the visual viewport, so an open keyboard cannot hide the bar', () => {
    const viewport = fakeVisualViewport({ height: 780, offsetTop: 0 });
    renderSheet();
    const dialog = screen.getByRole('dialog');

    // Closed keyboard: the sheet is the whole visible area.
    expect(dialog.style.height).toBe('780px');
    expect(dialog.style.top).toBe('0px');

    // iOS does not shrink the layout viewport for the keyboard — it shrinks the
    // visual one and scrolls the page under it, which is exactly how Done ends
    // up above the top edge of the screen. Following the visual viewport is the
    // only thing that keeps the bar where the user can tap it.
    viewport.emit({ height: 420, offsetTop: 160 });
    expect(dialog.style.height).toBe('420px');
    expect(dialog.style.top).toBe('160px');
  });

  it('stops listening to the viewport once it closes', () => {
    const viewport = fakeVisualViewport({ height: 780, offsetTop: 0 });
    const { view } = renderSheet();
    view.unmount();
    expect(viewport.listenerCount()).toBe(0);
  });

  it('does not let a tap on the bar dismiss the keyboard first', () => {
    renderSheet();
    // A tap that moves focus off the field closes the iOS keyboard, and the
    // layout reflow that follows swallows the click: the user taps Done, the
    // keyboard goes away and nothing is saved.
    for (const name of ['Cancel', 'Done']) {
      const notPrevented = fireEvent.mouseDown(screen.getByRole('button', { name }));
      expect(notPrevented).toBe(false);
    }
  });

  it('scrolls only the content, keeping both bar actions on screen', () => {
    renderSheet();
    const dialog = screen.getByRole('dialog');
    const scroll = dialog.querySelector('[data-sheet-scroll]');
    expect(scroll).not.toBeNull();
    expect(scroll!.className).toContain('overflow-y-auto');
    // The bar must sit outside the scrolling region, otherwise scrolling the
    // form under an open keyboard carries Cancel/Done away with it.
    for (const name of ['Cancel', 'Done']) {
      expect(screen.getByRole('button', { name }).closest('[data-sheet-scroll]')).toBeNull();
    }
    // The field, on the other hand, lives inside it.
    expect(screen.getByLabelText('Notes').closest('[data-sheet-scroll]')).not.toBeNull();
  });
});

describe('FullScreenSheet error banner', () => {
  it('shows the failure inside the sheet, above the form', () => {
    renderSheet({ error: 'server exploded' });
    const banner = screen.getByText('server exploded');
    const scroll = screen.getByRole('dialog').querySelector('[data-sheet-scroll]')!;

    // Inside the sheet, or the user never sees it: the sheet covers the page.
    expect(banner.closest('[data-sheet-scroll]')).not.toBeNull();
    // And first, so it is not scrolled out of sight below a long form.
    expect(scroll.firstElementChild!.contains(banner)).toBe(true);
  });

  it('renders no banner while nothing has failed', () => {
    renderSheet({ error: null });
    expect(screen.queryByText('Something went wrong')).toBeNull();
  });

  it('lets the user dismiss the failure', () => {
    const onDismissError = mock(() => {});
    renderSheet({ error: 'server exploded', onDismissError });
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss error' }));
    expect(onDismissError).toHaveBeenCalledTimes(1);
  });
});

describe('FullScreenSheet modal behaviour', () => {
  it('closes on Escape, the keyboard equivalent of Cancel', () => {
    const { onCancel } = renderSheet();
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('moves focus into the form when it opens', () => {
    renderSheet();
    expect(document.activeElement).toBe(screen.getByLabelText('Notes'));
  });

  it('wraps Tab from the last control back to the first', () => {
    renderSheet();
    const dialog = screen.getByRole('dialog');
    const notes = screen.getByLabelText('Notes');
    const cancel = screen.getByRole('button', { name: 'Cancel' });

    notes.focus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(document.activeElement).toBe(cancel);
  });

  it('wraps Shift+Tab from the first control to the last', () => {
    renderSheet();
    const dialog = screen.getByRole('dialog');
    const notes = screen.getByLabelText('Notes');
    const cancel = screen.getByRole('button', { name: 'Cancel' });

    cancel.focus();
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(notes);
  });

  it('freezes the page behind it and thaws it again on close', () => {
    const before = document.body.style.overflow;
    const { view } = renderSheet();
    expect(document.body.style.overflow).toBe('hidden');

    view.unmount();
    expect(document.body.style.overflow).toBe(before);
  });
});
