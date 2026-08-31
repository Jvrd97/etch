'use client';
// [review:need-review] PHASE-01/44-mobile-journal, PHASE-03/109, PHASE-03/nav-drawer
// summary: the row styling moved to lib/ui-constants as `navRowClass` — the desktop drawer draws the same row, and two copies of it drift apart on the first restyle
// summary: "More" screen of the mobile shell — links to the screens missing from the tab bar (a screen with a mobile version opens its /m twin, e.g. Journal) plus an escape hatch to the desktop version of the current screen and "Выйти"

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { ChevronRight, Monitor } from 'lucide-react';
import LogoutButton from '@/components/LogoutButton';
import { MORE_ROUTES } from '@/lib/routes';
import { routeIcon } from '@/components/route-icons';
import { TAP_TARGET_PX, navRowClass } from '@/lib/ui-constants';
import { browserStorage, toDesktopEntryPath, toMobilePath, writeViewMode } from '@/lib/view-mode';

export default function MoreSheet() {
  const router = useRouter();
  const pathname = usePathname();

  // Leaving through this link is an explicit preference, so a cold start does
  // not bounce the user back into the mobile shell. The target is the desktop
  // twin of the current screen (`/m/today` -> `/today`); `/m/more` itself has
  // no desktop twin and falls back to the dashboard.
  const handleDesktop = () => {
    writeViewMode(browserStorage(), 'desktop');
    router.push(toDesktopEntryPath(pathname));
  };

  return (
    <div className="space-y-3">
      {MORE_ROUTES.map((route) => {
        const Icon = routeIcon(route.id);
        // A "More" screen that already has a mobile version (Journal) opens its
        // /m twin so the user stays in the mobile shell; the ones still without
        // one keep pointing at their desktop route until their slice lands.
        const href = toMobilePath(route.href) ?? route.href;
        return (
          <Link
            key={route.href}
            href={href}
            style={{ minHeight: TAP_TARGET_PX }}
            className={navRowClass}
          >
            <Icon className="w-5 h-5 text-lime" strokeWidth={2} />
            <span className="flex-1 text-sm font-medium">{route.name}</span>
            <ChevronRight className="w-4 h-4 text-text-disabled" strokeWidth={2} />
          </Link>
        );
      })}

      <button
        type="button"
        onClick={handleDesktop}
        style={{ minHeight: TAP_TARGET_PX }}
        className={`${navRowClass} mt-6`}
      >
        <Monitor className="w-5 h-5 text-text-secondary" strokeWidth={2} />
        <span className="flex-1 text-left text-sm font-medium">Desktop version</span>
        <ChevronRight className="w-4 h-4 text-text-disabled" strokeWidth={2} />
      </button>

      <LogoutButton
        className={`${navRowClass} text-text-secondary`}
      />
    </div>
  );
}
