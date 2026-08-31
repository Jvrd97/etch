// [review:need-review] PHASE-03/nav-drawer
// summary: tests for the desktop header and its drawer — the two anchors stay outside, the drawer opens from the button and closes by button, Escape and scrim, focus returns to the button, focus is trapped while open, the active screen is marked on its detail route, and the page behind is frozen

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NAV_DRAWER_CLOSE_LABEL, NAV_DRAWER_TITLE, NAV_MENU_LABEL } from '@/lib/ui-constants';
import { VIEW_MODE_STORAGE_KEY } from '@/lib/view-mode';

let pathname: string;

// Same process-wide replacement rule the other suites follow: the hooks the
// nav's children import have to stay present even when this component never
// reads them.
mock.module('next/navigation', () => ({
  usePathname: () => pathname,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: mock(() => {}), replace: mock(() => {}) }),
  useParams: () => ({}),
}));

// `LogoutButton` reaches `@/lib/api` for `authAPI`, and seventeen other suites
// replace that module process-wide with a partial mock that has no `authAPI` in
// it. Standing it in here keeps the header's shape honest — a real button named
// "Выйти" — without making this suite depend on whichever mock happened to be
// registered last.
mock.module('@/components/LogoutButton', () => ({
  default: ({ className }: { className?: string }) => (
    <button type="button" className={className} aria-label="Выйти" />
  ),
}));

const { default: Navigation } = await import('./Navigation');

beforeEach(() => {
  pathname = '/today';
  window.localStorage.clear();
  window.sessionStorage.clear();
  // Without a stored preference the ViewToggle mounted beside the button would
  // try to restore the mobile shell mid-test.
  window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, 'desktop');
});

afterEach(() => {
  cleanup();
  document.body.style.overflow = '';
});

function openDrawer() {
  fireEvent.click(screen.getByRole('button', { name: NAV_MENU_LABEL }));
  return screen.getByRole('dialog');
}

/**
 * Presence questions are answered with booleans and names rather than with the
 * nodes themselves: a failed `toBeNull()` on a live happy-dom element makes the
 * runner serialise the whole document, which buries the one line that matters
 * under a hundred megabytes of listener maps.
 */
function drawerIsOpen(): boolean {
  return screen.queryByRole('dialog') !== null;
}

function hasLink(name: string): boolean {
  return screen.queryByRole('link', { name }) !== null;
}

function focusedName(): string {
  const active = document.activeElement;
  return active?.getAttribute('aria-label') ?? active?.textContent ?? 'nothing';
}

function currentOf(role: 'link', name: string): string | null {
  return screen.getByRole(role, { name }).getAttribute('aria-current');
}

describe('the desktop header', () => {
  it('keeps only the two daily screens on screen', () => {
    render(<Navigation />);
    expect(hasLink('Today')).toBe(true);
    expect(hasLink('Быстрые отметки')).toBe(true);
    // Everything else is behind the button: seventeen pills do not fit the
    // 1216px the container leaves, and the ones past the edge were unreachable.
    expect(hasLink('Insights')).toBe(false);
    expect(hasLink('Day rules')).toBe(false);
  });

  it('marks the anchor the reader is on', () => {
    render(<Navigation />);
    expect(currentOf('link', 'Today')).toBe('page');
    expect(currentOf('link', 'Быстрые отметки')).toBeNull();
  });

  it('keeps the shell toggle mounted while the drawer is closed', () => {
    // The toggle carries the cold-start restore into /m. Moving it inside the
    // drawer would silence that restore for every reader who never opens it.
    render(<Navigation />);
    expect(screen.getByRole('button', { name: /Mobile/ })).toBeDefined();
  });
});

describe('the navigation drawer', () => {
  it('is absent until the button is pressed', () => {
    render(<Navigation />);
    expect(drawerIsOpen()).toBe(false);
    expect(
      screen.getByRole('button', { name: NAV_MENU_LABEL }).getAttribute('aria-expanded')
    ).toBe('false');
  });

  it('opens from the button, as a modal dialog', () => {
    render(<Navigation />);
    const dialog = openDrawer();
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(dialog.getAttribute('aria-label')).toBe(NAV_DRAWER_TITLE);
    expect(
      screen.getByRole('button', { name: NAV_MENU_LABEL }).getAttribute('aria-expanded')
    ).toBe('true');
  });

  it('lists every screen, under Russian headings', () => {
    render(<Navigation />);
    openDrawer();
    expect(screen.getAllByRole('heading').map((node) => node.textContent)).toEqual([
      NAV_DRAWER_TITLE,
      'День',
      'Данные',
      'Настройка',
    ]);
    // The screen the old row cut off is the point of the whole exercise.
    expect(hasLink('Day rules')).toBe(true);
  });

  it('marks the screen the reader is on, including its detail route', () => {
    pathname = '/day/2026-08-30';
    render(<Navigation />);
    openDrawer();
    expect(currentOf('link', 'Day')).toBe('page');
    expect(currentOf('link', 'Journal')).toBeNull();
  });

  it('closes from its own button, and hands focus back', () => {
    render(<Navigation />);
    openDrawer();
    fireEvent.click(screen.getByRole('button', { name: NAV_DRAWER_CLOSE_LABEL }));
    expect(drawerIsOpen()).toBe(false);
    expect(focusedName()).toBe(NAV_MENU_LABEL);
  });

  it('closes on Escape', () => {
    render(<Navigation />);
    openDrawer();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(drawerIsOpen()).toBe(false);
    expect(focusedName()).toBe(NAV_MENU_LABEL);
  });

  it('closes on a click outside, on the scrim', () => {
    render(<Navigation />);
    openDrawer();
    fireEvent.click(document.querySelector('[data-nav-scrim]')!);
    expect(drawerIsOpen()).toBe(false);
  });

  it('closes when the reader follows one of its links', () => {
    render(<Navigation />);
    openDrawer();
    fireEvent.click(screen.getByRole('link', { name: 'Insights' }));
    expect(drawerIsOpen()).toBe(false);
  });

  it('starts focus inside itself', () => {
    render(<Navigation />);
    openDrawer();
    expect(focusedName()).toBe(NAV_DRAWER_CLOSE_LABEL);
  });

  it('wraps Tab at the end of the panel instead of walking into the page', () => {
    render(<Navigation />);
    const dialog = openDrawer();
    const links = screen.getAllByRole('link');
    const last = links[links.length - 1];
    last.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(focusedName()).toBe(NAV_DRAWER_CLOSE_LABEL);
  });

  it('wraps Shift+Tab backwards from the first control', () => {
    render(<Navigation />);
    const dialog = openDrawer();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('pulls focus back in when it has drifted onto the page behind', () => {
    render(<Navigation />);
    const dialog = openDrawer();
    (document.activeElement as HTMLElement | null)?.blur();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('freezes the page behind it, and thaws it on close', () => {
    render(<Navigation />);
    openDrawer();
    expect(document.body.style.overflow).toBe('hidden');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(document.body.style.overflow).not.toBe('hidden');
  });
});
