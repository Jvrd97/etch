// [review:need-review] PHASE-01/62-mobile-onboarding-twin, PHASE-03/93, PHASE-03/111, PHASE-03/118, PHASE-03/134, PHASE-03/152
// summary: unit tests for the screen registry — unique ids, tab-bar order, "More" list is the complement of the tab bar, tab destinations and mobile header titles (Journal and Onboarding name their More-only mobile screens), and the chat's own registration: a mobile twin under "More" that leaves the five tab slots alone
// summary: unit tests for the screen registry — unique ids, tab-bar order, "More" list is the complement of the tab bar, tab destinations and mobile header titles (Journal and Onboarding name their More-only mobile screens)

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

  it('never flags nested mobile routes on a screen without a mobile version', () => {
    // `hasMobileNested` widens `hasMobile`; on its own it would whitelist
    // /journal/7 for a mobile shell that has no /m/journal to begin with.
    expect(APP_ROUTES.every((route) => !route.hasMobileNested || route.hasMobile)).toBe(true);
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

describe('the chat registration', () => {
  const chat = APP_ROUTES.find((route) => route.id === 'chat');

  it('is one entry in the registry, with a mobile twin of its own', () => {
    // Своей навигации чат не заводит: экран `/m/chat` попадает и в «More», и в
    // белый список мобильных маршрутов из одной этой записи.
    expect(chat).toBeDefined();
    expect(chat?.href).toBe('/chat');
    expect(chat?.hasMobile).toBe(true);
    expect(chat?.hasMobileNested).toBe(false);
  });

  it('lives under "More" and takes no tab slot', () => {
    expect(chat?.inTabBar).toBeNull();
    expect(TAB_BAR_ROUTES.some((route) => route.id === 'chat')).toBe(false);
    expect(MORE_ROUTES.some((route) => route.id === 'chat')).toBe(true);
  });

  it('leaves the tab bar at five slots, in the order it already had', () => {
    // Перестановка табов — отдельное решение при слиянии personal-os
    // (ADR-0017). Тест держит именно это: чат приехал, а таб-бар не тронут.
    expect(MOBILE_TABS.map((tab) => tab.name)).toEqual([
      'Today',
      'Entries',
      'Dashboard',
      'Categories',
      'More',
    ]);
  });
});

describe('MORE_ROUTES', () => {
  it('is exactly the screens missing from the tab bar', () => {
    expect(MORE_ROUTES.map((route) => route.id)).toEqual([
      'day',
      'life',
      'week',
      'goals',
      'roles',
      'quick-marks',
      'chat',
      'daily-summary',
      'table',
      'journal',
      'insights',
      'day-rules',
      'onboarding',
    ]);
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

  it('points the Entries tab at the mobile screen, not the desktop page', () => {
    expect(MOBILE_TABS.find((tab) => tab.name === 'Entries')?.href).toBe('/m/entries');
  });

  it('points the Categories tab at the mobile screen, not the desktop page', () => {
    expect(MOBILE_TABS.find((tab) => tab.name === 'Categories')?.href).toBe('/m/categories');
  });

  it('marks the Categories tab as owning the routes nested below it', () => {
    expect(MOBILE_TABS.find((tab) => tab.name === 'Categories')?.nested).toBe(true);
    expect(MOBILE_TABS.find((tab) => tab.name === 'Today')?.nested).toBe(false);
  });

  it('points the Dashboard tab at its own mobile address, not at the bare /m', () => {
    // `/m` — редирект на мобильный Today (#123); дашборд у себя на /m/dashboard.
    expect(MOBILE_TABS.find((tab) => tab.name === 'Dashboard')?.href).toBe('/m/dashboard');
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

  it('names the mobile entries screen', () => {
    expect(mobileScreenTitle('/m/entries')).toBe('Entries');
  });

  it('names the More screen', () => {
    expect(mobileScreenTitle(MORE_PATH)).toBe('More');
  });

  it('names the mobile categories screen', () => {
    expect(mobileScreenTitle('/m/categories')).toBe('Categories');
  });

  it('names the mobile journal screen, though it lives under More', () => {
    expect(mobileScreenTitle('/m/journal')).toBe('Journal');
  });

  it('names the mobile day-summary screen, though it lives under More', () => {
    expect(mobileScreenTitle('/m/daily-summary')).toBe('Day summary');
  });

  it('names the mobile onboarding screen, though it lives under More', () => {
    expect(mobileScreenTitle('/m/onboarding')).toBe('Onboarding');
  });

  it('keeps naming the screen on a category detail route', () => {
    expect(mobileScreenTitle('/m/categories/12')).toBe('Categories');
  });

  it('falls back to the app name on an unknown route', () => {
    expect(mobileScreenTitle('/m/nowhere')).toBe(DEFAULT_SCREEN_TITLE);
  });

  it('does not name a nested route of a screen that owns no children', () => {
    expect(mobileScreenTitle('/m/today/12')).toBe(DEFAULT_SCREEN_TITLE);
  });
});
