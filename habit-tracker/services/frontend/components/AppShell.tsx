'use client';
// [review:need-review] PHASE-01/40-mobile-shell-toggle-manifest-today, PHASE-03/109
// summary: picks the shell for the current route — desktop nav + centered main, or bare children so app/m/layout can own the whole viewport
// summary: /login gets no shell at all — a nav that links to screens the reader cannot open yet is worse than no nav

import { usePathname } from 'next/navigation';
import Navigation from '@/components/Navigation';
import { isMobilePath } from '@/lib/view-mode';
import { isLoginPath } from '@/lib/auth';

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  // The login screen owns the viewport: every nav destination behind it
  // answers 401 until the key is typed.
  if (isLoginPath(pathname) || isMobilePath(pathname)) return <>{children}</>;

  return (
    <>
      <Navigation />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">{children}</main>
    </>
  );
}
