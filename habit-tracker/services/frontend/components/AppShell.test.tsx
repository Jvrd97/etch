// [review:need-review] PHASE-03/nav-drawer
// summary: tests for the shell picker — the drawer belongs to the desktop shell only, and a /m route (or the login screen) still gets bare children, so the mobile tab bar and MoreSheet are untouched by the drawer

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import { NAV_MENU_LABEL } from '@/lib/ui-constants';
import { VIEW_MODE_STORAGE_KEY } from '@/lib/view-mode';

let pathname: string;

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

const { default: AppShell } = await import('./AppShell');

beforeEach(() => {
  pathname = '/today';
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, 'desktop');
});

afterEach(() => {
  cleanup();
});

/** Booleans rather than nodes: see the note in Navigation.test.tsx. */
function hasDrawerButton(): boolean {
  return screen.queryByRole('button', { name: NAV_MENU_LABEL }) !== null;
}

function hasDialog(): boolean {
  return screen.queryByRole('dialog') !== null;
}

function renderShell() {
  return render(
    <AppShell>
      <p>screen</p>
    </AppShell>
  );
}

describe('AppShell', () => {
  it('gives a desktop route the header with the drawer button', () => {
    renderShell();
    expect(hasDrawerButton()).toBe(true);
    expect(screen.getByText('screen')).toBeDefined();
  });

  it('leaves a mobile route to the mobile shell', () => {
    // The drawer is a desktop answer to a desktop problem. Under /m the tab bar
    // and its "More" screen already answer it, and a second navigation on top
    // of them is two of everything.
    pathname = '/m/today';
    renderShell();
    expect(hasDrawerButton()).toBe(false);
    expect(hasDialog()).toBe(false);
    expect(screen.getByText('screen')).toBeDefined();
  });

  it('leaves the mobile More screen alone too', () => {
    pathname = '/m/more';
    renderShell();
    expect(hasDrawerButton()).toBe(false);
  });

  it('puts no navigation on the login screen', () => {
    pathname = '/login';
    renderShell();
    expect(hasDrawerButton()).toBe(false);
  });
});
