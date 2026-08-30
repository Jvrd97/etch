// [review:need-review] PHASE-03/111, PHASE-03/118, PHASE-01/62-mobile-onboarding-twin
// summary: unit tests for view-mode helpers — desktop/mobile path mapping and persisted preference; every registry screen has a mobile twin again now that Chat has one, a nested route of a flat screen is the no-mobile example

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

  it('is true for the journal screen', () => {
    expect(hasMobileVersion('/journal')).toBe(true);
  });

  it('is true for the table screen', () => {
    expect(hasMobileVersion('/table')).toBe(true);
  });

  it('is true for the insights screen', () => {
    expect(hasMobileVersion('/insights')).toBe(true);
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

  it('maps the journal screen to its mobile twin', () => {
    expect(toMobilePath('/journal')).toBe('/m/journal');
  });

  it('maps the table screen to its mobile twin', () => {
    expect(toMobilePath('/table')).toBe('/m/table');
  });

  it('maps the insights screen to its mobile twin', () => {
    expect(toMobilePath('/insights')).toBe('/m/insights');
  });

  it('maps the onboarding screen to its mobile twin', () => {
    expect(toMobilePath('/onboarding')).toBe('/m/onboarding');
  });

  it('returns null for a nested route of a screen that has no detail version', () => {
    expect(toMobilePath('/today/12')).toBeNull();
  });

  it('returns null below the one nested segment the mobile screen serves', () => {
    expect(toMobilePath('/categories/12/anything')).toBeNull();
  });

  it('maps the desktop dashboard to the bare mobile prefix', () => {
    expect(toMobilePath('/')).toBe('/m');
  });
});

describe('root route mapping', () => {
  it('maps the desktop dashboard to the bare mobile prefix without a trailing slash', () => {
    // The root href is `/`, so a naive concat would yield `/m/`; the mobile
    // dashboard lives at the bare `/m`, and `/m/` would 404.
    expect(toMobilePath('/')).toBe('/m');
  });

  it('is idempotent on the bare mobile prefix', () => {
    expect(toMobilePath('/m')).toBe('/m');
  });

  it('maps the bare mobile prefix back to the desktop dashboard', () => {
    expect(toDesktopPath('/m')).toBe('/');
  });

  it('round-trips the root across shells', () => {
    expect(toDesktopPath(toMobilePath('/') as string)).toBe('/');
  });

  it('reports the dashboard as having a mobile version', () => {
    expect(hasMobileVersion('/')).toBe(true);
  });

  it('resolves the root into the mobile shell when mobile is on', () => {
    expect(resolvePath('/', 'mobile')).toBe('/m');
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

  it('keeps the user on journal, which now has a mobile screen', () => {
    expect(mobileEntryPath('/journal')).toBe('/m/journal');
  });

  it('keeps the user on insights, which now has a mobile screen', () => {
    expect(mobileEntryPath('/insights')).toBe('/m/insights');
  });

  it('keeps the user on the dashboard, which now has a mobile screen', () => {
    expect(mobileEntryPath('/')).toBe('/m');
  });

  it('falls back to the mobile home from a mobile-only screen', () => {
    expect(mobileEntryPath('/m/more')).toBe('/m');
  });

  it('is idempotent on a mobile screen that has a desktop twin', () => {
    expect(mobileEntryPath('/m/today')).toBe('/m/today');
  });

  it('never returns a desktop route', () => {
    for (const route of APP_ROUTES) {
      expect(isMobilePath(mobileEntryPath(route.href))).toBe(true);
    }
  });
});

describe('MOBILE_HOME', () => {
  it('is the mobile twin of the first registry screen that has one', () => {
    expect(MOBILE_HOME).toBe(
      toMobilePath(APP_ROUTES.filter((route) => route.hasMobile)[0].href) as string
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

  it('sends journal to its mobile twin when mobile is on', () => {
    expect(resolvePath('/journal', 'mobile')).toBe('/m/journal');
  });

  it('sends table to its mobile twin when mobile is on', () => {
    expect(resolvePath('/table', 'mobile')).toBe('/m/table');
  });

  it('sends insights to its mobile twin when mobile is on', () => {
    expect(resolvePath('/insights', 'mobile')).toBe('/m/insights');
  });

  it('keeps an unmapped nested route on desktop even when mobile is on', () => {
    expect(resolvePath('/today/12', 'mobile')).toBe('/today/12');
  });

  it('sends a mobile route back to desktop when mobile is off', () => {
    expect(resolvePath('/m/today', 'desktop')).toBe('/today');
  });

  it('sends the mobile entries screen back to desktop when mobile is off', () => {
    expect(resolvePath('/m/entries', 'desktop')).toBe('/entries');
  });

  it('sends the mobile insights screen back to desktop when mobile is off', () => {
    expect(resolvePath('/m/insights', 'desktop')).toBe('/insights');
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

  it('redirects on a cold start on journal, which now has a mobile twin', () => {
    expect(shouldRestoreMobile('/journal', 'mobile', false)).toBe(true);
  });

  it('redirects on a cold start on insights, which now has a mobile twin', () => {
    expect(shouldRestoreMobile('/insights', 'mobile', false)).toBe(true);
  });

  it('does not redirect when the route has no mobile twin', () => {
    // A nested route of a flat screen has no mobile version, so mobile mode
    // leaves it on desktop instead of bouncing it to a /m route that 404s.
    expect(shouldRestoreMobile('/today/12', 'mobile', false)).toBe(false);
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

  it('contains every screen that has a mobile version', () => {
    expect(MOBILE_ROUTES).toContain('/today');
    expect(MOBILE_ROUTES).toContain('/entries');
    expect(MOBILE_ROUTES).toContain('/categories');
    expect(MOBILE_ROUTES).toContain('/journal');
    expect(MOBILE_ROUTES).toContain('/table');
    expect(MOBILE_ROUTES).toContain('/insights');
  });

  it('again covers every screen in the registry — Chat was the last one left', () => {
    // The exception opened by #111 (`/chat` without a mobile twin) is closed by
    // #118. Asserted as "no screen is missing one" rather than as a list of
    // exceptions, so the next screen landing without a twin has to reopen this
    // test deliberately instead of quietly joining a list.
    expect(APP_ROUTES.filter((route) => !route.hasMobile).map((route) => route.id)).toEqual([]);
    expect([...MOBILE_ROUTES]).toEqual(APP_ROUTES.map((route) => route.href));
    expect(APP_ROUTES.every((route) => hasMobileVersion(route.href))).toBe(true);
  });

  it('maps the chat across to the screen the mobile shell actually has', () => {
    expect(MOBILE_ROUTES).toContain('/chat');
    expect(toMobilePath('/chat')).toBe('/m/chat');
  });
});

describe('mobile entry point', () => {
  it('is the single source the PWA manifest starts from', async () => {
    const { default: manifest } = await import('../app/manifest');
    expect(manifest().start_url).toBe(MOBILE_HOME);
  });

  it('renders the dashboard at the bare /m rather than redirecting away', async () => {
    const source = await Bun.file(new URL('../app/m/page.tsx', import.meta.url)).text();
    // /m is now the mobile dashboard (twin of `/`), sharing the desktop screen's
    // logic through the hook — not a redirect to some other landing screen.
    expect(source).toContain('useDashboard');
    expect(source).not.toContain('redirect(');
  });

  it('agrees with the path helper for the first mobile screen', () => {
    expect(MOBILE_HOME).toBe(mobileEntryPath(MOBILE_ROUTES[0]));
  });
});
