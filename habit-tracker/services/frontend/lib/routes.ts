// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: single registry of app screens — desktop nav, mobile tab bar, "More" list, mobile header titles and the mobile-route whitelist are all derived from it

/**
 * One screen of the app, described once for every navigation surface.
 *
 * Deliberately icon-free: this module is imported by server-only code
 * (`app/manifest.ts`), so it must stay clear of React and lucide. The id maps
 * to a glyph in `components/route-icons`.
 */
export interface AppRoute {
  /** Stable identifier, independent of the visible label. */
  id: string;
  /** Label shown in the nav, the tab bar and the mobile header. */
  name: string;
  /** Desktop route; the mobile twin is derived by `lib/view-mode`. */
  href: string;
  /** True once the screen has a real `/m` version. */
  hasMobile: boolean;
  /** Slot in the mobile tab bar (lower comes first), or null when it lives under "More". */
  inTabBar: number | null;
}

/**
 * URL prefix owned by the mobile instance (`app/m/*`). It lives here rather
 * than in `lib/view-mode` because the registry itself has to spell mobile
 * hrefs, and `lib/view-mode` already imports this module — `view-mode`
 * re-exports it so the path helpers stay the one import consumers need.
 */
export const MOBILE_PATH_PREFIX = '/m';

/** Route of the mobile-only "More" screen. */
export const MORE_PATH = `${MOBILE_PATH_PREFIX}/more`;

/** Id of the mobile-only "More" tab, which has no entry in `APP_ROUTES`. */
export const MORE_ROUTE_ID = 'more';

/** Every screen, in desktop navigation order. */
export const APP_ROUTES: readonly AppRoute[] = [
  { id: 'dashboard', name: 'Dashboard', href: '/', hasMobile: false, inTabBar: 2 },
  { id: 'today', name: 'Today', href: '/today', hasMobile: true, inTabBar: 0 },
  { id: 'table', name: 'Table', href: '/table', hasMobile: false, inTabBar: null },
  { id: 'categories', name: 'Categories', href: '/categories', hasMobile: false, inTabBar: 3 },
  { id: 'entries', name: 'Entries', href: '/entries', hasMobile: false, inTabBar: 1 },
  { id: 'journal', name: 'Journal', href: '/journal', hasMobile: false, inTabBar: null },
  { id: 'insights', name: 'Insights', href: '/insights', hasMobile: false, inTabBar: null },
];

/** Tab-bar screens in tab order; the mobile-only "More" tab is appended by the bar itself. */
export const TAB_BAR_ROUTES: readonly AppRoute[] = APP_ROUTES.filter(
  (route) => route.inTabBar !== null
).sort((a, b) => (a.inTabBar ?? 0) - (b.inTabBar ?? 0));

/** Screens that did not fit in the tab bar and are reachable through "More". */
export const MORE_ROUTES: readonly AppRoute[] = APP_ROUTES.filter(
  (route) => route.inTabBar === null
);

/** One destination of the mobile tab bar. The id resolves to an icon in the UI layer. */
export interface MobileTab {
  id: string;
  name: string;
  href: string;
}

/**
 * Tab destinations: the registry's tab-bar screens, each pointing at its mobile
 * twin when it has one and at the desktop route otherwise (cramped but working
 * until its slice lands), plus the mobile-only "More" tab.
 */
export const MOBILE_TABS: readonly MobileTab[] = [
  ...TAB_BAR_ROUTES.map((route) => ({
    id: route.id,
    name: route.name,
    href: route.hasMobile ? `${MOBILE_PATH_PREFIX}${route.href}` : route.href,
  })),
  { id: MORE_ROUTE_ID, name: 'More', href: MORE_PATH },
];

/** Header text of the mobile shell when the route is not a known screen. */
export const DEFAULT_SCREEN_TITLE = 'Habit Tracker';

/** Header text for a mobile route: the tab it belongs to, else the app name. */
export function mobileScreenTitle(pathname: string): string {
  return MOBILE_TABS.find((tab) => tab.href === pathname)?.name ?? DEFAULT_SCREEN_TITLE;
}
