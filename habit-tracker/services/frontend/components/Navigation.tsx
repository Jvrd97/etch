'use client';
// [review:need-review] PHASE-03/nav-drawer
// summary: desktop header — the drawer button, the logo, the two daily anchors (Today, Быстрые отметки), the shell toggle and "Выйти"; the other fifteen screens live in NavDrawer, and focus comes back to the button when it closes

import { useCallback, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Menu } from 'lucide-react';
import ViewToggle from '@/components/ViewToggle';
import LogoutButton from '@/components/LogoutButton';
import NavDrawer from '@/components/NavDrawer';
import { HEADER_ROUTES, HOME_PATH, isActiveRoute } from '@/lib/routes';
import { routeIcon } from '@/components/route-icons';
import { NAV_MENU_LABEL } from '@/lib/ui-constants';

/** Id the drawer answers to, so the button can name it in `aria-controls`. */
const DRAWER_ID = 'nav-drawer';

/**
 * The desktop shell's header.
 *
 * The row of every screen it used to be does not fit and cannot be made to: at
 * seventeen items the labels need about 2000px inside a container capped at
 * 1280px, so the tail was cut off by the page's `overflow-x-hidden` and the
 * last screens had no click leading to them at all. What stays on screen is
 * what is opened daily; everything else is one press of the drawer button away.
 *
 * `ViewToggle` stays mounted here rather than moving into the drawer, and that
 * is load-bearing rather than tidy: it carries the cold-start restore that
 * sends a reader who left in mobile mode back to `/m`, and a restore that only
 * runs while a panel happens to be open does not run at all.
 */
export default function Navigation() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Every way out of the drawer lands here, so focus returns to the control the
  // reader pressed instead of falling back to the top of the document.
  const close = useCallback(() => {
    setOpen(false);
    buttonRef.current?.focus();
  }, []);

  return (
    <>
      <nav
        aria-label="Main"
        className="sticky top-0 z-40 bg-background/90 backdrop-blur-md border-b border-white/5"
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between gap-2 h-16">
            <div className="flex items-center gap-2 min-w-0">
              <button
                ref={buttonRef}
                type="button"
                onClick={() => setOpen(true)}
                aria-label={NAV_MENU_LABEL}
                aria-haspopup="dialog"
                aria-expanded={open}
                aria-controls={DRAWER_ID}
                className="inline-flex items-center justify-center w-10 h-10 shrink-0 rounded-full text-text-secondary transition-colors duration-200 hover:text-text-primary hover:bg-white/5"
              >
                <Menu className="w-5 h-5" strokeWidth={2} />
              </button>

              <Link href={HOME_PATH} className="flex items-center gap-2 min-w-0 select-none">
                <span className="text-xl font-bold tracking-tight text-text-primary truncate">
                  Habit Tracker
                </span>
                <span
                  aria-hidden="true"
                  className="shrink-0 w-2 h-2 rounded-full bg-lime shadow-[0_0_10px_rgba(184,255,54,0.8)]"
                />
              </Link>
            </div>

            <div className="flex items-center gap-1 sm:gap-2">
              {HEADER_ROUTES.map((route) => {
                const Icon = routeIcon(route.id);
                const active = isActiveRoute(pathname, route);
                return (
                  <Link
                    key={route.id}
                    href={route.href}
                    aria-current={active ? 'page' : undefined}
                    className={`inline-flex items-center gap-2 px-3 sm:px-4 py-2 rounded-full text-sm font-medium transition-all duration-200 ${
                      active
                        ? 'bg-lime text-background shadow-[0_0_18px_rgba(184,255,54,0.25)]'
                        : 'text-text-secondary hover:text-text-primary hover:bg-white/5'
                    }`}
                  >
                    <Icon className="w-4 h-4 shrink-0" strokeWidth={2} />
                    {/*
                      Narrow desktop windows still exist — the mobile shell is a
                      preference, not a width — so below `md` the anchors shrink
                      to their glyphs. `sr-only` rather than `hidden`: the label
                      is what names the link, and a link named by nothing is a
                      link a screen reader cannot announce.
                    */}
                    <span className="sr-only md:not-sr-only">{route.name}</span>
                  </Link>
                );
              })}
              <span aria-hidden="true" className="w-px h-6 bg-white/10 mx-1" />
              <ViewToggle />
              <LogoutButton />
            </div>
          </div>
        </div>
      </nav>

      {open && <NavDrawer id={DRAWER_ID} pathname={pathname} onClose={close} />}
    </>
  );
}
