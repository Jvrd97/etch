// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: unit tests for the screen registry — unique ids, tab-bar order, "More" list is the complement of the tab bar, tab destinations and mobile header titles

import { describe, expect, it } from 'bun:test';
import {
  APP_ROUTES,
  DEFAULT_SCREEN_TITLE,
  MOBILE_TABS,
  MORE_PATH,
  MORE_ROUTE_ID,
  MORE_ROUTES,
  TAB_BAR_ROUTES,
  mobileScreenTitle,
} from './routes';

describe('APP_ROUTES', () => {
  it('has unique ids', () => {
    const ids = APP_ROUTES.map((route) => route.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('has unique hrefs', () => {
    const hrefs = APP_ROUTES.map((route) => route.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it('describes only desktop hrefs, never the /m twin', () => {
    expect(APP_ROUTES.every((route) => !route.href.startsWith('/m/'))).toBe(true);
  });
});

describe('TAB_BAR_ROUTES', () => {
  it('is ordered by the tab slot, Today first', () => {
    expect(TAB_BAR_ROUTES.map((route) => route.id)).toEqual([
      'today',
      'entries',
      'dashboard',
      'categories',
    ]);
  });

  it('leaves room for the mobile-only More tab', () => {
    expect(TAB_BAR_ROUTES).toHaveLength(4);
  });
});

describe('MORE_ROUTES', () => {
  it('is exactly the screens missing from the tab bar', () => {
    expect(MORE_ROUTES.map((route) => route.id)).toEqual(['table', 'journal', 'insights']);
  });

  it('does not overlap the tab bar', () => {
    const inBar = new Set(TAB_BAR_ROUTES.map((route) => route.id));
    expect(MORE_ROUTES.some((route) => inBar.has(route.id))).toBe(false);
  });
});

describe('MOBILE_TABS', () => {
  it('is the tab-bar screens plus the mobile-only More tab', () => {
    expect(MOBILE_TABS.map((tab) => tab.name)).toEqual([
      ...TAB_BAR_ROUTES.map((route) => route.name),
      'More',
    ]);
  });

  it('points a screen with a mobile version at its /m twin', () => {
    expect(MOBILE_TABS.find((tab) => tab.name === 'Today')?.href).toBe('/m/today');
  });

  it('keeps a screen without a mobile version on its desktop route', () => {
    expect(MOBILE_TABS.find((tab) => tab.name === 'Entries')?.href).toBe('/entries');
  });

  it('ends on the More screen', () => {
    expect(MOBILE_TABS[MOBILE_TABS.length - 1].href).toBe(MORE_PATH);
  });

  it('carries a stable id so the tab bar can look up its icon', () => {
    expect(MOBILE_TABS.map((tab) => tab.id)).toEqual([
      ...TAB_BAR_ROUTES.map((route) => route.id),
      MORE_ROUTE_ID,
    ]);
  });
});

describe('lib/ purity', () => {
  it('keeps UI dependencies out of the registry', async () => {
    // The registry is imported by server modules (`app/manifest.ts`), so it must
    // stay free of React/lucide — icons live in `components/route-icons`.
    const source = await Bun.file(new URL('./routes.ts', import.meta.url)).text();
    expect(source).not.toContain('lucide-react');
  });

  it('describes every screen without an icon field', () => {
    expect(APP_ROUTES.every((route) => !('icon' in route))).toBe(true);
  });
});

describe('mobileScreenTitle', () => {
  it('names the screen behind a mobile route', () => {
    expect(mobileScreenTitle('/m/today')).toBe('Today');
  });

  it('names the More screen', () => {
    expect(mobileScreenTitle(MORE_PATH)).toBe('More');
  });

  it('falls back to the app name on an unknown route', () => {
    expect(mobileScreenTitle('/m/nowhere')).toBe(DEFAULT_SCREEN_TITLE);
  });
});
