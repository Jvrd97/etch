// [review:need-review] PHASE-03/123
// summary: the first frame of Today — the shape of the button row and of the cards under it, drawn while the snapshot is in flight, instead of a full-screen spinner that hides the very thing the tab was opened for

/** How many placeholder buttons the row shows before the directory arrives. */
const PLACEHOLDER_BUTTONS = 5;

/** How many placeholder cards stand in for the categories under the row. */
const PLACEHOLDER_CARDS = 2;

/** Said to a screen reader, which cannot see that the shapes are placeholders. */
export const SKELETON_LABEL = 'Экран дня загружается';

export interface QuickMarkSkeletonProps {
  /** Draw on the mobile scale: a full-width row and taller cards. */
  compact?: boolean;
}

/**
 * The first frame, in the shape of the screen that is coming.
 *
 * A spinner is honest about the wait and useless about everything else: it
 * covers the whole screen, so for the length of the round trip there is nothing
 * to press, and the layout jumps when the real screen replaces it. The
 * placeholder keeps the geometry, so the button row lands where the eye is
 * already looking.
 *
 * Deliberately not interactive. A placeholder button that could be pressed
 * would be a tap sent for a mark whose id has not arrived.
 */
export default function QuickMarkSkeleton({ compact = false }: QuickMarkSkeletonProps) {
  const buttonSize = compact ? 'h-14 flex-1' : 'h-12 w-28';
  return (
    <div
      role="status"
      aria-label={SKELETON_LABEL}
      aria-busy="true"
      className="space-y-6 animate-pulse"
    >
      <div className="flex items-center gap-3">
        <div className="h-3 w-24 rounded-full bg-white/10" />
        <div className="flex-1 h-px bg-white/5" />
      </div>

      <div className="flex gap-3 flex-wrap">
        {Array.from({ length: PLACEHOLDER_BUTTONS }, (_, index) => (
          <div key={index} className={`${buttonSize} rounded-3xl bg-white/5`} />
        ))}
      </div>

      <div className="space-y-3">
        {Array.from({ length: PLACEHOLDER_CARDS }, (_, index) => (
          <div key={index} className="h-24 rounded-3xl bg-card border border-white/5" />
        ))}
      </div>
    </div>
  );
}
