'use client';
// [review:need-review] PHASE-03/179
// summary: the card that offers a raised ceiling — the reason it is being offered, the price of taking it printed in the same glance, and two buttons; nothing here raises anything by itself, and the card is absent far more often than not

import ErrorAlert from '@/components/ErrorAlert';
import { useProfileProposal } from '@/hooks/useProfileProposal';
import {
  ACCEPT_LABEL,
  DECLINE_LABEL,
  PROPOSAL_PRICE,
  PROPOSAL_TITLE,
  proposalLine,
} from '@/lib/day-profiles';

export interface ProfileProposalProps {
  /** Re-read the day after the answer: every number on it stands on the ceiling. */
  onSettled?: () => void;
  compact?: boolean;
}

/**
 * «До пятницы дедлайн X, поднять потолок до N часов?»
 *
 * Absent on almost every day, and that is the design: a card that appears on
 * every busy Tuesday is a card that gets clicked through, and clicking through
 * is exactly how «переработка = проигранный день» would quietly stop existing.
 *
 * The price is on the card rather than behind it. A person accepting a bent rule
 * has to read what the bend costs in the same glance as the offer.
 */
export default function ProfileProposal({
  onSettled,
  compact = false,
}: ProfileProposalProps) {
  const { proposal, saving, error, accept, decline } = useProfileProposal(onSettled);

  if (!proposal) return error ? <ErrorAlert message={error} /> : null;

  const card = `bg-card border border-warning/30 rounded-3xl ${compact ? 'p-4' : 'p-6'}`;

  return (
    <section className={card}>
      {error && <ErrorAlert message={error} />}
      <h2 className={`text-text-primary ${compact ? 'text-base' : 'text-lg'}`}>
        {PROPOSAL_TITLE}
      </h2>
      <p className="text-sm text-text-primary mt-1">{proposalLine(proposal)}</p>
      <p className="text-xs text-warning mt-1">{PROPOSAL_PRICE}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={saving}
          onClick={() => void accept()}
          className="text-sm px-4 py-2 rounded-xl bg-lime text-background disabled:opacity-50"
        >
          {ACCEPT_LABEL}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => void decline()}
          className="text-sm px-4 py-2 rounded-xl bg-surface text-text-secondary disabled:opacity-50"
        >
          {DECLINE_LABEL}
        </button>
      </div>
    </section>
  );
}
