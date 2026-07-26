'use client';
// [review:need-review] PHASE-01/49-device-acceptance-checklist
// summary: the mobile shell's single screen action — rendered by the screen but placed into the header bar through a portal, so the button never floats over the cards it would otherwise cover

import { useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { Plus } from 'lucide-react';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

/**
 * Id of the header element the action lands in.
 *
 * The layout owns the header and the screen owns the action, so the two meet
 * through the DOM rather than through a prop drilled down a route boundary
 * Next.js does not hand us.
 */
export const MOBILE_HEADER_ACTION_SLOT_ID = 'mobile-header-action';

/** The empty box in the header bar that `MobileHeaderAction` fills. */
export function MobileHeaderActionSlot() {
  return <div id={MOBILE_HEADER_ACTION_SLOT_ID} className="ml-auto flex items-center" />;
}

/**
 * The slot is written once by the layout and never replaced, so there is no
 * change to subscribe to — the store exists only to read the DOM safely.
 */
function subscribeToNothing(): () => void {
  return () => {};
}

/** `false` — looked, and this screen is rendered outside the mobile shell. */
function readSlot(): HTMLElement | false {
  return document.getElementById(MOBILE_HEADER_ACTION_SLOT_ID) ?? false;
}

/** `null` — nothing has been looked up yet, so draw nothing at all. */
function readNoSlotYet(): null {
  return null;
}

export interface MobileHeaderActionProps {
  /** Accessible name of the button; there is no visible text, only the icon. */
  label: string;
  onClick: () => void;
}

/**
 * The plus button of a mobile screen, drawn in the header instead of floating
 * above the list.
 *
 * It used to be a bottom-right FAB, and on a phone that is a lime disc parked
 * on top of the last card's edit and delete buttons — the one place where the
 * list is hardest to reach. The header has room to spare and never moves.
 *
 * Rendering happens in two steps on purpose: the slot only exists once the
 * layout is mounted, so the first pass draws nothing rather than flashing the
 * button in the middle of the page and yanking it up a frame later. Without a
 * slot at all — a screen rendered outside the mobile layout, as the tests do —
 * the button stays where it was written, so it is never simply missing.
 */
export default function MobileHeaderAction({ label, onClick }: MobileHeaderActionProps) {
  // The slot is a piece of the DOM this component does not own, so it is read
  // as an external store rather than copied into state from an effect: on the
  // server, and while hydrating, there is nothing to read yet.
  const slot = useSyncExternalStore(subscribeToNothing, readSlot, readNoSlotYet);

  if (slot === null) return null;

  const button = (
    <button
      onClick={onClick}
      aria-label={label}
      style={{ minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }}
      className="inline-flex items-center justify-center rounded-full bg-lime text-background transition-transform duration-200 active:scale-95"
    >
      <Plus className="w-5 h-5" strokeWidth={2.5} />
    </button>
  );

  return slot === false ? button : createPortal(button, slot);
}
