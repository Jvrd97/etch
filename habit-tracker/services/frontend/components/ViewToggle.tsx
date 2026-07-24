'use client';
// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: "Mobile" button in the desktop nav — persists the shell preference and sends the user to the mobile twin of the current screen, or to the mobile home when that screen has no twin yet

import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Smartphone } from 'lucide-react';
import {
  MOBILE_ROUTES,
  browserSessionStorage,
  browserStorage,
  hasMobileVersion,
  hasRestoredViewMode,
  markViewModeRestored,
  mobileEntryPath,
  readViewMode,
  resolvePath,
  shouldRestoreMobile,
  writeViewMode,
} from '@/lib/view-mode';

export default function ViewToggle() {
  const pathname = usePathname();
  const router = useRouter();
  // The current screen has a mobile twin; without one the button still works
  // and drops the user at the mobile home instead of going dead.
  const twinAvailable = hasMobileVersion(pathname);
  // Only a registry with zero mobile screens leaves nowhere to go.
  const mobileShellExists = MOBILE_ROUTES.length > 0;

  // Cold start only: a user who left the app in mobile mode lands back on
  // /m/<path> instead of the desktop layout. The "already done" marker lives in
  // sessionStorage rather than a ref, because AppShell drops the desktop nav
  // (and this component with it) under /m — a ref would reset on every hop back
  // to desktop and redirect /today straight into /m/today again.
  useEffect(() => {
    const session = browserSessionStorage();
    const alreadyRestored = hasRestoredViewMode(session);
    // Burn the one restore this session gets even when the landing route has no
    // mobile twin, so a later click on a route that does have one is treated as
    // navigation rather than a cold start.
    markViewModeRestored(session);
    if (!shouldRestoreMobile(pathname, readViewMode(browserStorage()), alreadyRestored)) return;
    router.replace(resolvePath(pathname, 'mobile'));
  }, [pathname, router]);

  // This button lives in the desktop nav only (AppShell renders no nav under
  // /m), so the destination is always the mobile shell.
  const handleToggle = () => {
    writeViewMode(browserStorage(), 'mobile');
    router.push(mobileEntryPath(pathname));
  };

  return (
    <button
      type="button"
      onClick={handleToggle}
      disabled={!mobileShellExists}
      title={twinAvailable ? 'Switch to the mobile layout' : 'Back to the mobile app'}
      className="inline-flex items-center gap-2 px-3 sm:px-4 py-2 rounded-full text-sm font-medium border border-white/10 text-text-secondary transition-all duration-200 hover:text-text-primary hover:bg-white/5 disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-text-secondary"
    >
      <Smartphone className="w-4 h-4" strokeWidth={2} />
      <span className="hidden sm:inline">Mobile</span>
    </button>
  );
}
