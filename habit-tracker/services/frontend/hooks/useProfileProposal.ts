'use client';
// [review:need-review] PHASE-03/179
// summary: state of the proposal card — one read of the current offer, an accept that confirms an activation and a refuse that records the refusal so the same reason does not come back tomorrow; the card disappears either way

import { useCallback, useEffect, useState } from 'react';
import { profilesAPI, type ProfileProposal } from '@/lib/api';

/** Shown when the proposal cannot be read; the card then simply does not appear. */
export const LOAD_PROPOSAL_ERROR = 'Не удалось прочитать предложение по потолку';

export interface UseProfileProposalResult {
  proposal: ProfileProposal | null;
  saving: boolean;
  error: string | null;
  accept: () => Promise<void>;
  decline: () => Promise<void>;
}

/**
 * The current offer to raise the work ceiling, and the two answers to it.
 *
 * Accepting writes a confirmed activation — the only thing in the system that
 * moves a ceiling. Refusing writes the same row unconfirmed and declined, which
 * is what stops the same reason from being offered again tomorrow; a proposal a
 * person has to refuse daily is one they eventually accept.
 *
 * `onSettled` re-reads the day, because the ceiling the day is judged by has
 * just changed and every number on the screen stands on it.
 */
export function useProfileProposal(onSettled?: () => void): UseProfileProposalResult {
  const [proposal, setProposal] = useState<ProfileProposal | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const current = await profilesAPI.proposal();
        if (!cancelled) setProposal(current);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : LOAD_PROPOSAL_ERROR);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const answer = useCallback(
    async (act: () => Promise<unknown>) => {
      setSaving(true);
      setError(null);
      try {
        await act();
        setProposal(null);
        onSettled?.();
      } catch (err) {
        setError(err instanceof Error ? err.message : LOAD_PROPOSAL_ERROR);
      } finally {
        setSaving(false);
      }
    },
    [onSettled]
  );

  const accept = useCallback(async () => {
    if (!proposal) return;
    await answer(() =>
      profilesAPI.activate({
        profile_code: proposal.profile_code,
        valid_from: proposal.valid_from,
        valid_to: proposal.valid_to,
        reason: proposal.reason,
        source_signal_id: proposal.source_signal_id,
      })
    );
  }, [answer, proposal]);

  const decline = useCallback(async () => {
    if (!proposal) return;
    // Отказ пишется той же строкой, но неподтверждённой: сам факт отказа —
    // это то, из-за чего то же предложение не придёт завтра снова.
    await answer(async () => {
      const created = await profilesAPI.activate({
        profile_code: proposal.profile_code,
        valid_from: proposal.valid_from,
        valid_to: proposal.valid_to,
        reason: proposal.reason,
        source_signal_id: proposal.source_signal_id,
      });
      await profilesAPI.decline(created.id);
    });
  }, [answer, proposal]);

  return { proposal, saving, error, accept, decline };
}
