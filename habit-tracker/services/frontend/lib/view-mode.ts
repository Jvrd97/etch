// [review:need-review] PHASE-01/42-mobile-categories-and-detail
// summary: pure view-mode helpers — desktop/mobile route mapping over the screen registry (now including nested detail routes such as /categories/12) plus the persisted user preference

import { APP_ROUTES, MOBILE_PATH_PREFIX, isNestedMobileRoute } from './routes';

/** Which shell the user wants: the desktop layout or the `/m/*` mobile instance. */
export type ViewMode = 'desktop' | 'mobile';

export { MOBILE_PATH_PREFIX };

/**
 * localStorage key holding the user's shell preference — which of the two
 * shells renders the app. Per-screen layout preferences are a different
 * concept and live under their own `habit-tracker:<screen>-layout` keys.
 */
export const VIEW_MODE_STORAGE_KEY = 'habit-tracker:view-mode';

/**
 * sessionStorage key marking that this tab session already performed the
 * cold-start restore into the mobile shell. Scoped to the session on purpose:
 * the component driving the restore unmounts whenever the mobile shell takes
 * over, so a component-local flag would reset and bounce the user back to `/m`
 * every time they returned to the desktop layout.
 */
export const VIEW_MODE_RESTORED_SESSION_KEY = 'habit-tracker:view-mode-restored';

/** Value stored under `VIEW_MODE_RESTORED_SESSION_KEY`; only its presence matters. */
const RESTORED_MARKER = '1';

/**
 * Desktop routes that already have a mobile screen under `/m`, taken from the
 * screen registry. Everything else stays on the desktop layout even while
 * mobile mode is on — a half-built mobile route is worse than a cramped
 * desktop one.
 */
export const MOBILE_ROUTES: readonly string[] = APP_ROUTES.filter(
  (route) => route.hasMobile
).map((route) => route.href);

/**
 * Whitelisted routes whose mobile screen also serves one level below them, so
 * `/categories/12` maps across as readily as `/categories` does. The nesting
 * predicate is `lib/routes`' own, so the tab bar and this whitelist cannot
 * disagree about which screens own their children.
 */
const NESTED_MOBILE_ROUTES: readonly string[] = APP_ROUTES.filter(
  isNestedMobileRoute
).map((route) => route.href);

/**
 * True when `desktopPath` is `parent` plus exactly one more segment.
 *
 * The mobile detail screens are a single dynamic segment (`/m/categories/[id]`),
 * so anything deeper has no mobile route at all: a prefix test would map
 * `/categories/12/anything` onto a 404 instead of leaving the user on the
 * desktop page that does render it.
 */
function isDirectChild(desktopPath: string, parent: string): boolean {
  if (!desktopPath.startsWith(`${parent}/`)) return false;
  const rest = desktopPath.slice(parent.length + 1);
  return rest.length > 0 && !rest.includes('/');
}

/**
 * The whitelisted route serving `desktopPath` — itself when it is one, else the
 * nesting parent that owns it. Null when the mobile shell has no screen for it.
 */
function mobileRouteFor(desktopPath: string): string | null {
  if (MOBILE_ROUTES.includes(desktopPath)) return desktopPath;
  return NESTED_MOBILE_ROUTES.find((parent) => isDirectChild(desktopPath, parent)) ?? null;
}

/**
 * Landing screen of the mobile instance — the first registry screen that has a
 * mobile version, so the fallback follows the registry instead of a hardcoded
 * path. Degrades to the bare prefix only in the degenerate case of a registry
 * with no mobile screens at all.
 */
export const MOBILE_HOME: string =
  MOBILE_ROUTES.length > 0
    ? `${MOBILE_PATH_PREFIX}${MOBILE_ROUTES[0]}`
    : MOBILE_PATH_PREFIX;

/** Minimal slice of the Web Storage API these helpers need. */
export interface ViewModeStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** Drop a trailing slash so `/today/` and `/today` compare equal (root stays `/`). */
function normalize(pathname: string): string {
  if (pathname.length > 1 && pathname.endsWith('/')) return pathname.slice(0, -1);
  return pathname;
}

/** True when `pathname` is served by the mobile instance. */
export function isMobilePath(pathname: string): boolean {
  const path = normalize(pathname);
  return path === MOBILE_PATH_PREFIX || path.startsWith(`${MOBILE_PATH_PREFIX}/`);
}

/** The desktop route behind `pathname`, whichever side it currently sits on. */
export function toDesktopPath(pathname: string): string {
  const path = normalize(pathname);
  if (!isMobilePath(path)) return path;
  const stripped = path.slice(MOBILE_PATH_PREFIX.length);
  return stripped === '' ? '/' : stripped;
}

/**
 * Where the "desktop version" escape hatch should land from `pathname`: the
 * desktop twin of the current screen, so `/m/today` keeps the user on `/today`.
 * Mobile-only screens (`/m/more`) have no desktop counterpart and fall back to
 * the dashboard instead of pushing a 404.
 */
export function toDesktopEntryPath(pathname: string): string {
  const desktop = toDesktopPath(pathname);
  if (APP_ROUTES.some((route) => route.href === desktop)) return desktop;
  // A detail route is a real desktop screen too, and dropping its id would land
  // the user on the dashboard instead of the record they were reading.
  return mobileRouteFor(desktop) !== null ? desktop : '/';
}

/**
 * Mirror of `toDesktopEntryPath`: where the "mobile" entry point should land
 * from `pathname` — the mobile twin of the current screen when it has one, so
 * `/today` keeps the user on `/today`. Screens without a mobile version fall
 * back to `MOBILE_HOME` rather than blocking the way into the mobile shell.
 */
export function mobileEntryPath(pathname: string): string {
  return toMobilePath(pathname) ?? MOBILE_HOME;
}

/** True when the route behind `pathname` has a mobile screen. */
export function hasMobileVersion(pathname: string): boolean {
  return mobileRouteFor(toDesktopPath(pathname)) !== null;
}

/**
 * The mobile twin of `pathname`, or `null` when that route has no mobile screen
 * yet. Already-mobile paths map to themselves, and a nested route keeps its own
 * segments — `/categories/12` becomes `/m/categories/12`, not `/m/categories`.
 */
export function toMobilePath(pathname: string): string | null {
  const desktop = toDesktopPath(pathname);
  if (mobileRouteFor(desktop) === null) return null;
  return `${MOBILE_PATH_PREFIX}${desktop}`;
}

/**
 * Where `pathname` should live under `mode`. Falls back to the desktop route
 * when mobile mode is on but the route is not whitelisted.
 */
export function resolvePath(pathname: string, mode: ViewMode): string {
  if (mode === 'desktop') return toDesktopPath(pathname);
  return toMobilePath(pathname) ?? toDesktopPath(pathname);
}

/**
 * Whether a cold-start redirect into the mobile shell is due for `pathname`.
 *
 * True only for the first restore of a tab session (`alreadyRestored` is the
 * session marker, not a component-local flag) when the user left the app in
 * mobile mode and the current route actually has a different mobile twin.
 * Every later navigation reports false, so clicking a desktop nav link — or
 * pressing Back from `/m/today` to `/today` — keeps the user on desktop
 * instead of being thrown straight back into `/m`.
 *
 * Accepted trade-off: the session marker is burned on the first run of the
 * effect, redirect or not. A cold start on a route with no mobile twin
 * (`/journal`, say) with `mode=mobile` stored therefore spends the marker
 * without moving anywhere, and the user stays on the desktop shell until the
 * tab session ends — they have to press `Mobile` once. The opposite bias, a
 * marker set only when the redirect actually fires, brings back the loop where
 * every return to the desktop layout counts as a cold start and bounces the
 * user into `/m`, which is the worse failure.
 */
export function shouldRestoreMobile(
  pathname: string,
  mode: ViewMode,
  alreadyRestored: boolean
): boolean {
  if (alreadyRestored) return false;
  if (mode !== 'mobile') return false;
  const path = normalize(pathname);
  return resolvePath(path, 'mobile') !== path;
}

/** True when this tab session already ran the cold-start restore. */
export function hasRestoredViewMode(storage: ViewModeStorage | null | undefined): boolean {
  return storage?.getItem(VIEW_MODE_RESTORED_SESSION_KEY) != null;
}

/** Record that the cold-start restore ran; a missing storage (SSR) is a silent no-op. */
export function markViewModeRestored(storage: ViewModeStorage | null | undefined): void {
  storage?.setItem(VIEW_MODE_RESTORED_SESSION_KEY, RESTORED_MARKER);
}

/** The browser's sessionStorage, or `null` when running on the server. */
export function browserSessionStorage(): ViewModeStorage | null {
  if (typeof window === 'undefined') return null;
  return window.sessionStorage;
}

/** Stored preference, defaulting to desktop when absent, corrupted, or on the server. */
export function readViewMode(storage: ViewModeStorage | null | undefined): ViewMode {
  const stored = storage?.getItem(VIEW_MODE_STORAGE_KEY);
  return stored === 'mobile' ? 'mobile' : 'desktop';
}

/** True when the user has already expressed a shell preference. */
export function hasStoredViewMode(storage: ViewModeStorage | null | undefined): boolean {
  const stored = storage?.getItem(VIEW_MODE_STORAGE_KEY);
  return stored === 'mobile' || stored === 'desktop';
}

/**
 * Record `mode` only when nothing was stored yet, and report whether it wrote.
 * Landing on a `/m` route (a PWA cold start through the manifest `start_url`,
 * say) may seed the preference, but must never overwrite a choice the user
 * already made — otherwise a back-button hop into the mobile shell would flip
 * the app to mobile for good.
 */
export function seedViewMode(
  storage: ViewModeStorage | null | undefined,
  mode: ViewMode
): boolean {
  if (hasStoredViewMode(storage)) return false;
  writeViewMode(storage, mode);
  return true;
}

/** Persist the preference; a missing storage (SSR) is a silent no-op. */
export function writeViewMode(
  storage: ViewModeStorage | null | undefined,
  mode: ViewMode
): void {
  storage?.setItem(VIEW_MODE_STORAGE_KEY, mode);
}

/** The browser's localStorage, or `null` when running on the server. */
export function browserStorage(): ViewModeStorage | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage;
}
