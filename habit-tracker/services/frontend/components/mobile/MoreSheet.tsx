'use client';
// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: "More" screen of the mobile shell — links to the screens missing from the tab bar plus an escape hatch to the desktop version of the current screen

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { ChevronRight, Monitor } from 'lucide-react';
import { MORE_ROUTES } from '@/lib/routes';
import { routeIcon } from '@/components/route-icons';
import { TAP_TARGET_PX } from '@/lib/ui-constants';
import { browserStorage, toDesktopEntryPath, writeViewMode } from '@/lib/view-mode';

const ROW_CLASS =
  'flex items-center gap-3 w-full px-4 py-3 bg-card border border-white/5 rounded-2xl text-text-primary transition-colors duration-200 active:bg-white/5';

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
        return (
          <Link
            key={route.href}
            href={route.href}
            style={{ minHeight: TAP_TARGET_PX }}
            className={ROW_CLASS}
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
        className={`${ROW_CLASS} mt-6`}
      >
        <Monitor className="w-5 h-5 text-text-secondary" strokeWidth={2} />
        <span className="flex-1 text-left text-sm font-medium">Desktop version</span>
        <ChevronRight className="w-4 h-4 text-text-disabled" strokeWidth={2} />
      </button>
    </div>
  );
}
