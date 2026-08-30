'use client';
// [review:need-review] PHASE-03/121, PHASE-03/122
// summary: the Today row of quick-mark buttons — one button per row of the directory, one tap sends the button's id and nothing else, the total under the label comes from the tap's own answer, and on a shell that has a keyboard the button prints the key that fires it

import type { QuickMark } from '@/lib/api';
import { markActionLabel, markCaption } from '@/lib/quick-marks';
import { hotkeyAssignment } from '@/lib/quick-mark-hotkeys';
import { TAP_TARGET_PX } from '@/lib/ui-constants';

interface QuickMarkRowProps {
  /** The directory as the server returned it, already ordered. */
  marks: QuickMark[];
  /**
   * Record one tap of `id`. The row does not know what the button means —
   * that is the server's answer — so it sends nothing but the id.
   */
  onTap: (id: number) => void;
  /**
   * Print the key each button answers to. Only the desktop shell asks for it:
   * it is the one that listens for those keys, and a key drawn in the mobile
   * shell would name something there is no keyboard to press.
   */
  showHotkeys?: boolean;
}

/**
 * The quick-mark buttons of Today.
 *
 * Renders nothing at all for an empty directory: buttons are entered by hand,
 * and a screen that says "заведи кнопку" would be a permanent instruction on a
 * page whose whole purpose is to be tapped and left.
 *
 * A button carries three things: the label the user gave it, the day's total
 * under it, and whether the day already counts it as done. What it writes,
 * which field it writes to and whether it accumulates are deliberately absent —
 * that knowledge lives on the server, which is what keeps the floating window
 * of the agent from having to reimplement it.
 *
 * With `showHotkeys` it carries a fourth: the key. It is read from the same
 * assignment table the keydown handler resolves through, so what is printed and
 * what fires cannot disagree; a button that has no key prints none.
 */
export default function QuickMarkRow({ marks, onTap, showHotkeys = false }: QuickMarkRowProps) {
  if (marks.length === 0) return null;

  const hotkeys = hotkeyAssignment(marks);

  return (
    <div className="flex flex-wrap gap-3">
      {marks.map((mark, index) => {
        const caption = markCaption(mark);
        const hotkey = showHotkeys ? hotkeys[index] : null;
        return (
          <button
            key={mark.id}
            type="button"
            onClick={() => onTap(mark.id)}
            aria-label={markActionLabel(mark)}
            aria-pressed={mark.done}
            style={{ minHeight: TAP_TARGET_PX }}
            className={`inline-flex flex-col items-start justify-center gap-0.5 px-5 py-3 rounded-3xl border text-left transition-all duration-200 ${
              mark.done
                ? 'bg-lime text-background border-lime shadow-[0_0_18px_rgba(184,255,54,0.25)]'
                : 'bg-card text-text-secondary border-white/10 hover:text-text-primary hover:bg-white/5'
            }`}
          >
            <span className="inline-flex items-center gap-2">
              {hotkey !== null && (
                // Hidden from assistive tech: the button already announces
                // itself through aria-label, and a key nobody can press with a
                // screen reader open is noise in that announcement.
                <kbd
                  aria-hidden="true"
                  className={`px-1.5 py-0.5 rounded-md border text-[10px] font-medium leading-none ${
                    mark.done ? 'border-background/30 text-background' : 'border-white/15'
                  }`}
                >
                  {hotkey}
                </kbd>
              )}
              <span className="text-sm font-medium truncate">{mark.label}</span>
            </span>
            {caption && (
              // Keyed by the caption so a change remounts the node and replays
              // the animation: on rapid taps a restyled node keeps the finished
              // animation and later increments land silently.
              <span
                key={caption}
                className="text-xs tabular-nums opacity-80 animate-total-bump"
              >
                {caption}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
