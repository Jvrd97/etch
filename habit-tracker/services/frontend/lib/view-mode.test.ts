// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
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

  it('is false for a route without a mobile screen yet', () => {
    expect(hasMobileVersion('/entries')).toBe(false);
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

  it('returns null for a route without a mobile version', () => {
    expect(toMobilePath('/entries')).toBeNull();
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
});

describe('mobileEntryPath', () => {
  it('keeps the user on the same screen when it exists on mobile', () => {
    expect(mobileEntryPath('/today')).toBe('/m/today');
  });

  it('falls back to the mobile home for a screen without a mobile twin', () => {
    expect(mobileEntryPath('/entries')).toBe('/m/today');
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

  it('keeps an unmapped route on desktop even when mobile is on', () => {
    expect(resolvePath('/entries', 'mobile')).toBe('/entries');
  });

  it('sends a mobile route back to desktop when mobile is off', () => {
    expect(resolvePath('/m/today', 'desktop')).toBe('/today');
  });

  it('leaves a desktop route alone when mobile is off', () => {
    expect(resolvePath('/entries', 'desktop')).toBe('/entries');
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
    expect(shouldRestoreMobile('/entries', 'mobile', false)).toBe(false);
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

  it('contains /today and nothing that lacks a mobile screen', () => {
    expect(MOBILE_ROUTES).toContain('/today');
    expect(MOBILE_ROUTES).not.toContain('/entries');
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
