'use client';
// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today
// summary: picks the shell for the current route — desktop nav + centered main, or bare children so app/m/layout can own the whole viewport

import { usePathname } from 'next/navigation';
import Navigation from '@/components/Navigation';
import { isMobilePath } from '@/lib/view-mode';

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (isMobilePath(pathname)) return <>{children}</>;

  return (
    <>
      <Navigation />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">{children}</main>
    </>
  );
}
