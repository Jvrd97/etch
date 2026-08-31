// [review:need-review] PHASE-03/179
// summary: pure labels of the breathing ceiling — the line that says which profile judges this day and until when, the sentence a proposal is read as, the debt printed as hours with the day it came from, and the rule that a debt older than a week is a failed rule rather than a note

import type { DebtLedger, OvertimeDebt, ProfileInForce, ProfileProposal, Week } from '@/lib/api';
import { formatMinutes } from '@/lib/day-format';
import { countable } from '@/lib/plural';

/** Past this a debt is not a note any more. */
export const STALE_DEBT_DAYS = 7;

/** Headings and labels of the two blocks. */
export const PROPOSAL_TITLE = 'Поднять потолок?';
export const ACCEPT_LABEL = 'Принять';
export const DECLINE_LABEL = 'Нет';
export const DEBT_TITLE = 'Долг за переработку';
export const NO_DEBT_TEXT = 'Долга за переработку нет';

/**
 * What the raise costs, said on the card that offers it.
 *
 * On the card and not in a tooltip: «переработка = проигранный день» is the rule
 * being bent, and a person accepting the bend has to read the price in the same
 * glance as the offer.
 */
export const PROPOSAL_PRICE =
  'Поднятый потолок создаёт долг: неделя не выиграна, пока он не вернулся.';

/** Why an old debt is drawn as a failure. */
export const STALE_DEBT_TEXT = 'висит дольше недели — это проваленное правило, а не справка';

/**
 * Which ceiling this day is judged by, or null on an ordinary day.
 *
 * Null on the baseline deliberately: a line saying «обычный потолок» on every
 * ordinary day is a line nobody reads, and then the one day it says something
 * else is not noticed either.
 */
export function profileLine(profile: ProfileInForce | null): string | null {
  if (!profile || profile.valid_to === null) return null;
  return `${profile.title}: потолок ${formatMinutes(profile.work_cap_min)} до ${profile.valid_to}`;
}

/** The offer as one sentence: what is proposed, until when, and why. */
export function proposalLine(proposal: ProfileProposal): string {
  return `${proposal.reason}. Потолок ${formatMinutes(proposal.work_cap_min)} до ${proposal.valid_to}?`;
}

/** One debt as the week block prints it. */
export function debtLine(debt: OvertimeDebt): string {
  if (!debt.is_open) {
    return `${debt.incurred_on}: ${formatMinutes(debt.minutes_over)} — вернулось ${debt.repaid_on}`;
  }
  return `${debt.incurred_on}: ${formatMinutes(debt.minutes_over)} — ${countable(
    debt.days_open,
    'день',
    'дня',
    'дней'
  )} не возвращено`;
}

/** Whether this debt has been open long enough to read as a failed rule. */
export function isStale(debt: OvertimeDebt): boolean {
  return debt.is_open && debt.days_open > STALE_DEBT_DAYS;
}

/** Debts worth drawing: the open ones first, then what came back. */
export function ledgerRows(ledger: DebtLedger): OvertimeDebt[] {
  return [...ledger.debts].sort((left, right) => {
    if (left.is_open !== right.is_open) return left.is_open ? -1 : 1;
    return left.incurred_on < right.incurred_on ? -1 : 1;
  });
}

/**
 * Why a week of won days is still not won, or null when it is.
 *
 * The sentence exists because the number alone is confusing: «7 из 7» beside
 * «не выиграна» reads as a bug until something says the debt is the reason.
 */
export function weekBlockedLine(week: Week): string | null {
  if (week.is_won || week.debt_minutes === 0) return null;
  return `Неделя не выиграна: ${formatMinutes(week.debt_minutes)} переработки не вернулись.`;
}
