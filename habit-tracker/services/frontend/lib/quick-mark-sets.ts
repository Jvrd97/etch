// [review:need-review] PHASE-01/206
// summary: the wording of a day's sets — what one set says it was worth, the heading and the card entry for a number against a tick

import type { QuickMark, QuickMarkDayEvent } from '@/lib/api';
import { formatMarkTotal } from '@/lib/quick-marks';

/** What a tick that set the box says in the list. */
export const TICKED = 'Отмечено';

/** What a tick that cleared the box says in the list. */
export const UNTICKED = 'Снято';

/**
 * What one set was worth, as the row prints it.
 *
 * A number is signed — "+25", "-400" — because the row is a move of the day's
 * total, not a total of its own. A tick has no quantity, so it says which way
 * it moved the box. A row with neither figure prints nothing rather than a zero:
 * a zero would be a claim about the set.
 */
export function setAmount(event: QuickMarkDayEvent): string {
  if (event.bool_value !== null) return event.bool_value ? TICKED : UNTICKED;
  if (event.delta === null) return '';
  const figure = formatMarkTotal(event.delta);
  const signed = event.delta > 0 ? `+${figure}` : figure;
  return event.unit_label ? `${signed} ${event.unit_label}` : signed;
}

/** The heading of the list: a number is counted in sets, a tick in marks. */
export function daySetsHeading(mark: QuickMark): string {
  return mark.kind === 'check' ? 'Отметки за сегодня' : 'Подходы за сегодня';
}

/**
 * The accessible name of the part of a card that opens the list.
 *
 * It starts with the heading rather than the button's label so that it never
 * equals the name of the button beside it, which is the label alone: two nodes
 * sharing a name are the same node to a reader who navigates by name.
 */
export function daySetsOpenLabel(mark: QuickMark): string {
  return `${daySetsHeading(mark)} — ${mark.label}`;
}
