// [review:need-review] PHASE-01/60-quick-plus-tap-adds-one
// summary: pure parser for the Today quick-add tap — turns the input field's contents into the amount to log, or null for "do nothing"

/** What a tap logs when the field is left empty: one of whatever is being counted. */
const IMPLICIT_AMOUNT = 1;

interface QuickAddState {
  /**
   * Whether the control is holding text it could not parse as a number. A
   * `type="number"` input reports an empty `value` in that case, so without this
   * flag "abc" looks exactly like an untouched field and would log a `1`.
   */
  hasBadInput: boolean;
}

/**
 * The amount one tap of the "+" should record, or `null` when the tap must do
 * nothing at all.
 *
 * An empty field is the common case — a glass of water, a cigarette — and means
 * `1`. A typed number is logged as-is, negatives included: subtracting is the
 * only way to fix a typo without leaving the screen. Zero and anything that is
 * not a number are ignored silently: there is no entry worth writing, and an
 * error toast for a stray keystroke would be noise.
 */
export function quickAddAmount(
  input: string,
  { hasBadInput }: QuickAddState = { hasBadInput: false }
): number | null {
  if (hasBadInput) return null;

  const trimmed = input.trim();
  if (trimmed === '') return IMPLICIT_AMOUNT;

  const amount = Number(trimmed);
  if (!Number.isFinite(amount) || amount === 0) return null;
  return amount;
}
