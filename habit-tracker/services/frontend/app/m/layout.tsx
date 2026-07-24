'use client';
// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: mobile shell — screen-title header, scrollable content column, bottom tab bar; seeds the mobile preference on a first visit only

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import TabBar from '@/components/mobile/TabBar';
import { mobileScreenTitle } from '@/lib/routes';
import { browserStorage, seedViewMode } from '@/lib/view-mode';

export default function MobileLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  // A first visit to the mobile shell (a PWA launched straight at the manifest
  // start_url, say) seeds the preference so the next cold start stays mobile.
  // It must not overwrite an existing choice: otherwise going Back into /m or
  // following an external /m link would switch the app to mobile for good.
  useEffect(() => {
    seedViewMode(browserStorage(), 'mobile');
  }, []);

  return (
    <div className="min-h-screen flex flex-col overflow-x-hidden">
      <header className="sticky top-0 z-40 bg-background/95 backdrop-blur-md border-b border-white/5 pt-[env(safe-area-inset-top)]">
        <div className="flex items-center gap-2 h-14 px-4">
          <h1 className="text-lg font-bold tracking-tight text-text-primary truncate">
            {mobileScreenTitle(pathname)}
          </h1>
          <span
            aria-hidden="true"
            className="w-2 h-2 rounded-full bg-lime shadow-[0_0_10px_rgba(184,255,54,0.8)]"
          />
        </div>
      </header>

      <main className="flex-1 w-full px-4 pt-4 pb-24">{children}</main>

      <TabBar />
    </div>
  );
}
