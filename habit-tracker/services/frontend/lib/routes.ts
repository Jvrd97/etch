// [review:need-review] PHASE-01/73-daily-summary-metrics-vertical, PHASE-03/86, PHASE-03/93
// summary: single registry of app screens — desktop nav, mobile tab bar, "More" list, mobile header titles and the mobile-route whitelist are all derived from it; every screen has a mobile twin, Categories owns its nested detail route, Day summary/Goals/Journal/Table/Insights/Onboarding reached through "More"

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
  /**
   * True when that `/m` version also serves the routes nested below `href` —
   * `/categories/12` as well as `/categories`. Kept separate from `hasMobile`
   * because most screens are flat: whitelisting `/today/12` would send the user
   * to a mobile route that does not exist. Meaningless without `hasMobile`.
   */
  hasMobileNested: boolean;
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
  {
    id: 'dashboard',
    name: 'Dashboard',
    href: '/',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: 2,
  },
  {
    id: 'today',
    name: 'Today',
    href: '/today',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: 0,
  },
  {
    id: 'day',
    name: 'Day',
    href: '/day',
    hasMobile: true,
    // `/day/2026-08-30` is a real screen on both shells, and the bare `/day`
    // is the same screen for today — the nesting flag is what carries the date
    // across when the reader switches shells.
    hasMobileNested: true,
    // Under "More": the day screen is opened on purpose, from a link with a
    // date on it, and the tab bar's five slots are already spoken for.
    inTabBar: null,
  },
  {
    id: 'goals',
    name: 'Goals',
    href: '/goals',
    hasMobile: true,
    hasMobileNested: false,
    // Under "More": the goals are read when a quarter turns or a milestone
    // closes, not several times a day, and the tab bar's five slots are already
    // spoken for.
    inTabBar: null,
  },
  {
    id: 'daily-summary',
    name: 'Day summary',
    href: '/daily-summary',
    hasMobile: true,
    hasMobileNested: false,
    // First of the "More" screens: telling the app about your day is a daily
    // act, but the tab bar's five slots are already spoken for.
    inTabBar: null,
  },
  {
    id: 'table',
    name: 'Table',
    href: '/table',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: null,
  },
  {
    id: 'categories',
    name: 'Categories',
    href: '/categories',
    hasMobile: true,
    hasMobileNested: true,
    inTabBar: 3,
  },
  {
    id: 'entries',
    name: 'Entries',
    href: '/entries',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: 1,
  },
  {
    id: 'journal',
    name: 'Journal',
    href: '/journal',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: null,
  },
  {
    id: 'insights',
    name: 'Insights',
    href: '/insights',
    hasMobile: true,
    hasMobileNested: false,
    inTabBar: null,
  },
  {
    id: 'onboarding',
    name: 'Onboarding',
    href: '/onboarding',
    hasMobile: true,
    hasMobileNested: false,
    // Last of the "More" screens on purpose: setting categories up by talking
    // at the app is a rare act, not a daily one, and the tab bar's five slots
    // are already spoken for.
    inTabBar: null,
  },
];

/**
 * Whether the screen's mobile version also serves the routes nested below it.
 *
 * `hasMobileNested` widens `hasMobile` and is meaningless without it, so the
 * conjunction is spelled once here: both the tab bar (which keeps a tab lit on
 * its detail screens) and `lib/view-mode` (which whitelists those detail routes)
 * ask the same question, and two copies of it drift into a tab that highlights a
 * route the router refuses to map.
 */
export function isNestedMobileRoute(route: AppRoute): boolean {
  return route.hasMobile && route.hasMobileNested;
}

/**
 * The `/m` twin of a screen's desktop href. The root `/` maps to the bare `/m`,
 * not `/m/`: a plain concat would leave a trailing slash that maps onto no
 * route. Only meaningful for a route whose `hasMobile` is true.
 */
export function mobileHref(route: AppRoute): string {
  return `${MOBILE_PATH_PREFIX}${route.href === '/' ? '' : route.href}`;
}

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
  /** True when the tab also covers the routes nested under `href`. */
  nested: boolean;
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
    // A tab-bar screen without a mobile version yet points at its desktop route
    // (cramped but working); one with a mobile version points at its `/m` twin.
    href: route.hasMobile ? mobileHref(route) : route.href,
    nested: isNestedMobileRoute(route),
  })),
  { id: MORE_ROUTE_ID, name: 'More', href: MORE_PATH, nested: false },
];

/**
 * Deep link that opens an Entries screen with its editor already up.
 *
 * Both Entries screens read it and both shells link to it, so the literal lives
 * here rather than in any one of them: a rename in four unconnected places is a
 * dead "+" button on whichever shell was missed.
 */
export const NEW_ENTRY_PARAM = 'new';
export const NEW_ENTRY_VALUE = '1';
export const NEW_ENTRY_QUERY = `?${NEW_ENTRY_PARAM}=${NEW_ENTRY_VALUE}`;

/** Whether a screen's query string asks for the editor to open on mount. */
export function wantsNewEntry(params: { get(name: string): string | null }): boolean {
  return params.get(NEW_ENTRY_PARAM) === NEW_ENTRY_VALUE;
}

/** Header text of the mobile shell when the route is not a known screen. */
export const DEFAULT_SCREEN_TITLE = 'Habit Tracker';

/**
 * Header text for a mobile route: the tab it belongs to, else the app name.
 *
 * A tab that owns its nested routes keeps naming the header on them, so
 * `/m/categories/12` reads "Categories" instead of dropping to the app name the
 * moment the user opens a detail screen.
 */
export function mobileScreenTitle(pathname: string): string {
  const tab =
    MOBILE_TABS.find((candidate) => candidate.href === pathname) ??
    MOBILE_TABS.find(
      (candidate) => candidate.nested && pathname.startsWith(`${candidate.href}/`)
    );
  if (tab) return tab.name;
  // A mobile screen reachable only through "More" (Journal) has no tab, so its
  // header would otherwise drop to the app name. Name it from the registry.
  const screen = APP_ROUTES.find((route) => route.hasMobile && mobileHref(route) === pathname);
  return screen?.name ?? DEFAULT_SCREEN_TITLE;
}
