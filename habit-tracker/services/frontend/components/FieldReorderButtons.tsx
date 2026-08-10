'use client';
// [review:need-review] PHASE-01/73-category-field-reorder
// summary: the up/down pair that moves a field row in the category editor — one owner of the accessible names both shells' tests read, of the disabled-at-the-ends rule, and of the focus that follows the row it just moved

import { useEffect, useRef } from 'react';
import { ArrowDown, ArrowUp } from 'lucide-react';
import type { FieldMoveDirection } from '@/hooks/useCategories';
import { TAP_TARGET_PX, reorderButtonClass } from '@/lib/ui-constants';

/**
 * Accessible name of a reorder button.
 *
 * The single source both shells render from. These names are the only handle a
 * screen reader — and every test of either editor — has on the row's controls,
 * and two shells that spell them differently are two apps to anyone who cannot
 * see the arrows.
 */
export function moveFieldLabel(position: number, direction: FieldMoveDirection): string {
  return `Move field ${position} ${direction}`;
}

export interface FieldReorderButtonsProps {
  /** 1-based position of the row, as it reads in the accessible names. */
  position: number;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMove: (direction: FieldMoveDirection) => void;
  /**
   * Size the buttons as touch targets rather than as desktop icon buttons.
   *
   * The mobile sheet owes every control `TAP_TARGET_PX`; the desktop modal has
   * a pointer and would only waste the row's width on it.
   */
  touch?: boolean;
}

/**
 * Move this field up or down, with the focus following it.
 *
 * The rows are keyed by draft row, so the pressed button travels with its row
 * to the new position — and at either end of the list it lands there disabled,
 * which drops focus to the document and strands anyone working from the
 * keyboard. After a move, focus goes to the button that still does something:
 * the one just pressed if it is still live, otherwise its opposite, which is
 * the control that undoes the move.
 */
export default function FieldReorderButtons({
  position,
  canMoveUp,
  canMoveDown,
  onMove,
  touch = false,
}: FieldReorderButtonsProps) {
  const upRef = useRef<HTMLButtonElement>(null);
  const downRef = useRef<HTMLButtonElement>(null);
  /** Direction of the move this component started, until its row has landed. */
  const pending = useRef<FieldMoveDirection | null>(null);

  useEffect(() => {
    const direction = pending.current;
    if (direction === null) return;
    pending.current = null;
    const preferred = direction === 'up' ? upRef.current : downRef.current;
    const fallback = direction === 'up' ? downRef.current : upRef.current;
    (preferred?.disabled ? fallback : preferred)?.focus();
  }, [position]);

  const move = (direction: FieldMoveDirection) => {
    pending.current = direction;
    onMove(direction);
  };

  const sizing = touch
    ? { style: { minHeight: TAP_TARGET_PX, minWidth: TAP_TARGET_PX }, className: reorderButtonClass }
    : { style: undefined, className: `${reorderButtonClass} p-2` };

  return (
    <>
      <button
        ref={upRef}
        type="button"
        onClick={() => move('up')}
        disabled={!canMoveUp}
        aria-label={moveFieldLabel(position, 'up')}
        style={sizing.style}
        className={sizing.className}
      >
        <ArrowUp className="w-4 h-4" strokeWidth={2} />
      </button>
      <button
        ref={downRef}
        type="button"
        onClick={() => move('down')}
        disabled={!canMoveDown}
        aria-label={moveFieldLabel(position, 'down')}
        style={sizing.style}
        className={sizing.className}
      >
        <ArrowDown className="w-4 h-4" strokeWidth={2} />
      </button>
    </>
  );
}
