'use client';
// [review:need-review] PHASE-03/nav-drawer
// summary: desktop navigation drawer — every screen of the registry grouped under День/Данные/Настройка, the active one marked on its detail routes too, and the modal contract its role promises: Escape, focus trap, frozen page behind, click on the scrim closes

import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { ChevronRight, X } from 'lucide-react';
import { NAV_SECTIONS, isActiveRoute } from '@/lib/routes';
import { routeIcon } from '@/components/route-icons';
import { focusablesIn, trapTab } from '@/lib/focus-trap';
import {
  NAV_DRAWER_CLOSE_LABEL,
  NAV_DRAWER_TITLE,
  TAP_TARGET_PX,
  navRowClass,
} from '@/lib/ui-constants';

export interface NavDrawerProps {
  /** DOM id, so the button that opens the drawer can point `aria-controls` at it. */
  id: string;
  /** Current route, which decides the marked row. */
  pathname: string;
  /**
   * Close the drawer. Every path out calls it — Escape, the scrim, the close
   * button, following a link — because returning focus to the opening button is
   * the caller's job and it has exactly one place to do it.
   */
  onClose: () => void;
}

/** Row of a screen the reader is not currently on. */
const IDLE_ROW = 'border-white/5 text-text-primary hover:bg-white/5';

/**
 * Row of the screen the reader is on.
 *
 * Tinted rather than filled with lime: the header pill is one item among four
 * and can afford a solid block, while a full-width solid row inside a list of
 * seventeen reads as a banner instead of a mark.
 */
const ACTIVE_ROW = 'bg-lime/10 border-lime/40 text-text-primary';

/**
 * The desktop navigation, off screen until asked for.
 *
 * Mounted only while open, so "closed" is the absence of the dialog rather than
 * a hidden copy of it: nothing behind the scrim can be tabbed into, and the
 * `aria-modal` promise does not have to be maintained in two states.
 *
 * The keyboard listener sits on `document` rather than on the panel. A
 * container-bound handler only fires while focus is inside, and a click on the
 * panel's own padding puts focus on `body` — after which Escape would stop
 * working with the drawer still open on screen.
 */
export default function NavDrawer({ id, pathname, onClose }: NavDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Scrolling the page behind an open drawer is the classic modal bug: the
  // panel stays put while the screen underneath drifts away.
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  // Focus starts on the close button — the first control in the panel — so the
  // reader who opened the drawer from the keyboard can dismiss it with the very
  // next keystroke, and so Tab has somewhere inside to start from.
  useEffect(() => {
    focusablesIn(panelRef.current)[0]?.focus();
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === 'Tab') trapTab(event, panelRef.current);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <>
      {/* Decorative: closing by clicking outside is a shortcut, and the two
          real controls — Escape and the close button — are keyboard-reachable,
          so the scrim itself stays out of the accessibility tree. */}
      <div
        data-nav-scrim
        aria-hidden="true"
        onClick={onClose}
        className="fixed inset-0 z-40 bg-background/70 backdrop-blur-sm animate-scrim-in"
      />

      <div
        id={id}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={NAV_DRAWER_TITLE}
        className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-white/5 bg-background animate-drawer-in"
      >
        <div className="flex h-16 items-center justify-between gap-2 border-b border-white/5 px-4">
          <h2 className="text-sm font-semibold tracking-tight text-text-primary">
            {NAV_DRAWER_TITLE}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={NAV_DRAWER_CLOSE_LABEL}
            style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
            className="-mr-2 inline-flex items-center justify-center rounded-full text-text-secondary transition-colors duration-200 hover:bg-white/5 hover:text-text-primary"
          >
            <X className="w-5 h-5" strokeWidth={2} />
          </button>
        </div>

        <nav aria-label="Экраны" className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
          {NAV_SECTIONS.map((section) => (
            <section key={section.id} aria-labelledby={`${id}-${section.id}`}>
              <h3
                id={`${id}-${section.id}`}
                className="px-2 pb-2 text-[11px] font-semibold uppercase tracking-wider text-text-disabled"
              >
                {section.name}
              </h3>
              <ul className="space-y-2">
                {section.routes.map((route) => {
                  const Icon = routeIcon(route.id);
                  const active = isActiveRoute(pathname, route);
                  return (
                    <li key={route.id}>
                      <Link
                        href={route.href}
                        onClick={onClose}
                        aria-current={active ? 'page' : undefined}
                        style={{ minHeight: TAP_TARGET_PX }}
                        className={`${navRowClass} ${active ? ACTIVE_ROW : IDLE_ROW}`}
                      >
                        <Icon
                          className={`w-5 h-5 ${active ? 'text-lime' : 'text-text-secondary'}`}
                          strokeWidth={2}
                        />
                        <span className="flex-1 text-sm font-medium">{route.name}</span>
                        <ChevronRight className="w-4 h-4 text-text-disabled" strokeWidth={2} />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </nav>
      </div>
    </>
  );
}
