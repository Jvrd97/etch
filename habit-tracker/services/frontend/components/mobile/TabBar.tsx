'use client';
// [review:need-review] PHASE-01/42-mobile-categories-and-detail
// summary: bottom tab bar of the mobile shell — pure rendering of MOBILE_TABS from lib/routes, 44pt tap targets; a tab owning nested routes stays highlighted on them

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MOBILE_TABS } from '@/lib/routes';
import { routeIcon } from '@/components/route-icons';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

export default function TabBar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Main"
      className="fixed bottom-0 inset-x-0 z-40 bg-background/95 backdrop-blur-md border-t border-white/5 pb-[env(safe-area-inset-bottom)]"
    >
      <ul className="flex items-stretch justify-around">
        {MOBILE_TABS.map((tab) => {
          const Icon = routeIcon(tab.id);
          // A detail screen belongs to the tab that owns it, so /m/categories/12
          // keeps Categories lit instead of leaving no tab marked at all.
          const isActive =
            pathname === tab.href || (tab.nested && pathname.startsWith(`${tab.href}/`));
          return (
            <li key={tab.href} className="flex-1">
              <Link
                href={tab.href}
                aria-current={isActive ? 'page' : undefined}
                style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
                className={`flex flex-col items-center justify-center gap-1 h-14 px-1 text-[11px] font-medium transition-colors duration-200 ${
                  isActive ? 'text-lime' : 'text-text-secondary'
                }`}
              >
                <Icon className="w-5 h-5" strokeWidth={2} />
                <span className="truncate">{tab.name}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
