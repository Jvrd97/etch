// [review:need-review] PHASE-01/41-mobile-entries-fullscreen-sheet, PHASE-01/42-mobile-categories-and-detail
// summary: unit tests for view-mode helpers — desktop/mobile path mapping and persisted preference

import { describe, expect, it } from 'bun:test';
import { APP_ROUTES } from './routes';
import {
  MOBILE_HOME,
  MOBILE_PATH_PREFIX,
  MOBILE_ROUTES,
  VIEW_MODE_RESTORED_SESSION_KEY,
  VIEW_MODE_STORAGE_KEY,
  hasMobileVersion,
  hasStoredViewMode,
  hasRestoredViewMode,
  isMobilePath,
  markViewModeRestored,
  mobileEntryPath,
  readViewMode,
  resolvePath,
  seedViewMode,
  shouldRestoreMobile,
  toDesktopEntryPath,
  toDesktopPath,
  toMobilePath,
  writeViewMode,
  type ViewModeStorage,
} from './view-mode';

/** In-memory stand-in for `window.localStorage`. */
function makeStorage(initial: Record<string, string> = {}): ViewModeStorage & {
  dump(): Record<string, string>;
} {
  const data = { ...initial };
  return {
    getItem: (key) => data[key] ?? null,
    setItem: (key, value) => {
      data[key] = value;
    },
    dump: () => ({ ...data }),
  };
}

describe('isMobilePath', () => {
  it('recognises a mobile route', () => {
    expect(isMobilePath('/m/today')).toBe(true);
  });

  it('recognises the bare mobile prefix', () => {
    expect(isMobilePath(MOBILE_PATH_PREFIX)).toBe(true);
  });

  it('does not treat a same-letter desktop route as mobile', () => {
    expect(isMobilePath('/markdown')).toBe(false);
  });

  it('rejects a desktop route', () => {
    expect(isMobilePath('/today')).toBe(false);
  });
});

describe('hasMobileVersion', () => {
  it('is true for a whitelisted route', () => {
    expect(hasMobileVersion('/today')).toBe(true);
  });

  it('is true for a route already on the mobile side', () => {
    expect(hasMobileVersion('/m/today')).toBe(true);
  });

  it('is true for the entries screen', () => {
    expect(hasMobileVersion('/entries')).toBe(true);
  });

  it('is true for the categories screen', () => {
    expect(hasMobileVersion('/categories')).toBe(true);
  });

  it('is true for a category detail route', () => {
    expect(hasMobileVersion('/categories/12')).toBe(true);
  });

  it('is false for a route without a mobile screen yet', () => {
    expect(hasMobileVersion('/journal')).toBe(false);
  });

  it('does not treat a nested route of a flat screen as mobile', () => {
    expect(hasMobileVersion('/today/12')).toBe(false);
  });

  it('stops at one nested segment', () => {
    // `/m/categories/[id]` is a single dynamic segment; anything deeper is a
    // mobile route that does not exist, and claiming it does sends the user to
    // a 404 instead of leaving them on the working desktop page.
    expect(hasMobileVersion('/categories/12/anything')).toBe(false);
  });
});

describe('toMobilePath', () => {
  it('maps a whitelisted desktop route to its mobile twin', () => {
    expect(toMobilePath('/today')).toBe('/m/today');
  });

  it('is idempotent on a mobile route', () => {
    expect(toMobilePath('/m/today')).toBe('/m/today');
  });

  it('ignores a trailing slash', () => {
    expect(toMobilePath('/today/')).toBe('/m/today');
  });

  it('maps the entries screen to its mobile twin', () => {
    expect(toMobilePath('/entries')).toBe('/m/entries');
  });

  it('is idempotent on the mobile entries route', () => {
    expect(toMobilePath('/m/entries')).toBe('/m/entries');
  });

  it('carries the id of a category detail route across to mobile', () => {
    expect(toMobilePath('/categories/12')).toBe('/m/categories/12');
  });

  it('is idempotent on a mobile category detail route', () => {
    expect(toMobilePath('/m/categories/12')).toBe('/m/categories/12');
  });

  it('returns null for a route without a mobile version', () => {
    expect(toMobilePath('/journal')).toBeNull();
  });

  it('returns null for a nested route of a screen that has no detail version', () => {
    expect(toMobilePath('/today/12')).toBeNull();
  });

  it('returns null below the one nested segment the mobile screen serves', () => {
    expect(toMobilePath('/categories/12/anything')).toBeNull();
  });

  it('returns null for the desktop dashboard', () => {
    expect(toMobilePath('/')).toBeNull();
  });
});

describe('toDesktopPath', () => {
  it('strips the mobile prefix', () => {
    expect(toDesktopPath('/m/today')).toBe('/today');
  });

  it('is idempotent on a desktop route', () => {
    expect(toDesktopPath('/today')).toBe('/today');
  });

  it('maps the bare mobile prefix to the desktop dashboard', () => {
    expect(toDesktopPath('/m')).toBe('/');
  });

  it('leaves a same-letter desktop route untouched', () => {
    expect(toDesktopPath('/markdown')).toBe('/markdown');
  });
});

describe('toDesktopEntryPath', () => {
  it('keeps the user on the same screen when it exists on desktop', () => {
    expect(toDesktopEntryPath('/m/today')).toBe('/today');
  });

  it('falls back to the dashboard for a mobile-only screen', () => {
    expect(toDesktopEntryPath('/m/more')).toBe('/');
  });

  it('maps the bare mobile prefix to the dashboard', () => {
    expect(toDesktopEntryPath('/m')).toBe('/');
  });

  it('leaves a desktop route that is already a known screen alone', () => {
    expect(toDesktopEntryPath('/journal')).toBe('/journal');
  });

  it('keeps the user on the same category when leaving the detail screen', () => {
    // Dropping the id here would send someone reading /m/categories/12 back to
    // the dashboard instead of the very category they were looking at.
    expect(toDesktopEntryPath('/m/categories/12')).toBe('/categories/12');
  });

  it('falls back to the dashboard for a nested route of a flat screen', () => {
    expect(toDesktopEntryPath('/m/today/12')).toBe('/');
  });
});

describe('mobileEntryPath', () => {
  it('keeps the user on the same screen when it exists on mobile', () => {
    expect(mobileEntryPath('/today')).toBe('/m/today');
  });

  it('keeps the user on entries, which now has a mobile screen', () => {
    expect(mobileEntryPath('/entries')).toBe('/m/entries');
  });

  it('keeps the id when entering the mobile shell from a category detail page', () => {
    expect(mobileEntryPath('/categories/12')).toBe('/m/categories/12');
  });

  it('falls back to the mobile home for a screen without a mobile twin', () => {
    expect(mobileEntryPath('/journal')).toBe('/m/today');
  });

  it('falls back to the mobile home from the desktop dashboard', () => {
    expect(mobileEntryPath('/')).toBe('/m/today');
  });

  it('falls back to the mobile home from a mobile-only screen', () => {
    expect(mobileEntryPath('/m/more')).toBe('/m/today');
  });

  it('is idempotent on a mobile screen that has a desktop twin', () => {
    expect(mobileEntryPath('/m/today')).toBe('/m/today');
  });

  it('never returns a desktop route', () => {
    for (const route of APP_ROUTES) {
      expect(mobileEntryPath(route.href).startsWith(`${MOBILE_PATH_PREFIX}/`)).toBe(true);
    }
  });
});

describe('MOBILE_HOME', () => {
  it('is the mobile twin of the first registry screen that has one', () => {
    expect(MOBILE_HOME).toBe(
      `${MOBILE_PATH_PREFIX}${APP_ROUTES.filter((route) => route.hasMobile)[0].href}`
    );
  });

  it('is itself a mobile path', () => {
    expect(isMobilePath(MOBILE_HOME)).toBe(true);
  });
});

describe('resolvePath', () => {
  it('sends a desktop route to mobile when mobile is on', () => {
    expect(resolvePath('/today', 'mobile')).toBe('/m/today');
  });

  it('sends entries to its mobile twin when mobile is on', () => {
    expect(resolvePath('/entries', 'mobile')).toBe('/m/entries');
  });

  it('sends a category detail route to its mobile twin, id and all', () => {
    expect(resolvePath('/categories/12', 'mobile')).toBe('/m/categories/12');
  });

  it('sends a mobile category detail route back to desktop when mobile is off', () => {
    expect(resolvePath('/m/categories/12', 'desktop')).toBe('/categories/12');
  });

  it('keeps an unmapped route on desktop even when mobile is on', () => {
    expect(resolvePath('/journal', 'mobile')).toBe('/journal');
  });

  it('sends a mobile route back to desktop when mobile is off', () => {
    expect(resolvePath('/m/today', 'desktop')).toBe('/today');
  });

  it('sends the mobile entries screen back to desktop when mobile is off', () => {
    expect(resolvePath('/m/entries', 'desktop')).toBe('/entries');
  });

  it('leaves a desktop route alone when mobile is off', () => {
    expect(resolvePath('/journal', 'desktop')).toBe('/journal');
  });
});

describe('readViewMode', () => {
  it('defaults to desktop with no stored preference', () => {
    expect(readViewMode(makeStorage())).toBe('desktop');
  });

  it('reads back a stored mobile preference', () => {
    expect(readViewMode(makeStorage({ [VIEW_MODE_STORAGE_KEY]: 'mobile' }))).toBe('mobile');
  });

  it('falls back to desktop on a corrupted value', () => {
    expect(readViewMode(makeStorage({ [VIEW_MODE_STORAGE_KEY]: 'tablet' }))).toBe('desktop');
  });

  it('defaults to desktop when storage is unavailable (SSR)', () => {
    expect(readViewMode(null)).toBe('desktop');
  });
});

describe('writeViewMode', () => {
  it('persists the preference so it survives a restart', () => {
    const storage = makeStorage();
    writeViewMode(storage, 'mobile');
    expect(readViewMode(makeStorage(storage.dump()))).toBe('mobile');
  });

  it('overwrites a previous preference', () => {
    const storage = makeStorage({ [VIEW_MODE_STORAGE_KEY]: 'mobile' });
    writeViewMode(storage, 'desktop');
    expect(storage.dump()[VIEW_MODE_STORAGE_KEY]).toBe('desktop');
  });

  it('is a no-op when storage is unavailable (SSR)', () => {
    expect(() => writeViewMode(null, 'mobile')).not.toThrow();
  });
});

describe('hasStoredViewMode', () => {
  it('is false before the user ever chose a shell', () => {
    expect(hasStoredViewMode(makeStorage())).toBe(false);
  });

  it('is true once a preference was written', () => {
    expect(hasStoredViewMode(makeStorage({ [VIEW_MODE_STORAGE_KEY]: 'desktop' }))).toBe(true);
  });

  it('treats a corrupted value as no preference', () => {
    expect(hasStoredViewMode(makeStorage({ [VIEW_MODE_STORAGE_KEY]: 'tablet' }))).toBe(false);
  });

  it('is false when storage is unavailable (SSR)', () => {
    expect(hasStoredViewMode(null)).toBe(false);
  });
});

describe('seedViewMode', () => {
  it('stores the mode when nothing was chosen yet', () => {
    const storage = makeStorage();
    expect(seedViewMode(storage, 'mobile')).toBe(true);
    expect(readViewMode(storage)).toBe('mobile');
  });

  it('does not overwrite an explicit desktop preference', () => {
    const storage = makeStorage({ [VIEW_MODE_STORAGE_KEY]: 'desktop' });
    expect(seedViewMode(storage, 'mobile')).toBe(false);
    expect(readViewMode(storage)).toBe('desktop');
  });

  it('is a no-op when storage is unavailable (SSR)', () => {
    expect(() => seedViewMode(null, 'mobile')).not.toThrow();
  });
});

describe('shouldRestoreMobile', () => {
  it('redirects on a cold start with a stored mobile preference', () => {
    expect(shouldRestoreMobile('/today', 'mobile', false)).toBe(true);
  });

  it('does not redirect again once the session already restored', () => {
    // Regression: pressing Back from /m/today to /today must stay on desktop.
    expect(shouldRestoreMobile('/today', 'mobile', true)).toBe(false);
  });

  it('does not redirect when the stored preference is desktop', () => {
    expect(shouldRestoreMobile('/today', 'desktop', false)).toBe(false);
  });

  it('does not redirect when the route has no mobile twin', () => {
    expect(shouldRestoreMobile('/journal', 'mobile', false)).toBe(false);
  });

  it('does not redirect when already on the mobile side', () => {
    expect(shouldRestoreMobile('/m/today', 'mobile', false)).toBe(false);
  });

  it('ignores a trailing slash rather than bouncing /today/ to itself', () => {
    expect(shouldRestoreMobile('/today/', 'mobile', false)).toBe(true);
    expect(shouldRestoreMobile('/m/today/', 'mobile', false)).toBe(false);
  });
});

describe('session restore marker', () => {
  it('is unset before the first restore of the tab session', () => {
    expect(hasRestoredViewMode(makeStorage())).toBe(false);
  });

  it('reads back as set once marked', () => {
    const storage = makeStorage();
    markViewModeRestored(storage);
    expect(hasRestoredViewMode(storage)).toBe(true);
    expect(storage.dump()[VIEW_MODE_RESTORED_SESSION_KEY]).toBeDefined();
  });

  it('survives a remount within the same session, so the restore runs once', () => {
    const storage = makeStorage();
    markViewModeRestored(storage);
    // A fresh reader over the same session storage — i.e. ViewToggle remounted.
    expect(shouldRestoreMobile('/today', 'mobile', hasRestoredViewMode(makeStorage(storage.dump())))).toBe(
      false
    );
  });

  it('treats an unavailable storage (SSR) as not yet restored', () => {
    expect(hasRestoredViewMode(null)).toBe(false);
    expect(() => markViewModeRestored(null)).not.toThrow();
  });
});

describe('MOBILE_ROUTES', () => {
  it('is exactly the registry screens flagged as having a mobile version', () => {
    expect([...MOBILE_ROUTES]).toEqual(
      APP_ROUTES.filter((route) => route.hasMobile).map((route) => route.href)
    );
  });

  it('contains the screens that have a mobile version and nothing else', () => {
    expect(MOBILE_ROUTES).toContain('/today');
    expect(MOBILE_ROUTES).toContain('/entries');
    expect(MOBILE_ROUTES).toContain('/categories');
    expect(MOBILE_ROUTES).not.toContain('/journal');
  });
});

describe('mobile entry point', () => {
  it('is the single source the PWA manifest starts from', async () => {
    const { default: manifest } = await import('../app/manifest');
    expect(manifest().start_url).toBe(MOBILE_HOME);
  });

  it('is what the /m index redirects to', async () => {
    const source = await Bun.file(new URL('../app/m/page.tsx', import.meta.url)).text();
    // The redirect must read the registry, not spell a path of its own.
    expect(source).toContain('MOBILE_HOME');
    expect(source).not.toContain("redirect('/m/");
  });

  it('agrees with the path helper for the first mobile screen', () => {
    expect(MOBILE_HOME).toBe(mobileEntryPath(MOBILE_ROUTES[0]));
  });
});
