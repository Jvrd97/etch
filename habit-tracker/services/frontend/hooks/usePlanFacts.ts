'use client';
// [review:need-review] PHASE-03/200
// summary: the state of plan lines linked to categories — the facts each line wrote, kept from the day and replaced by every write's own answer, one write per line at a time, the key of an attempt whose answer was lost kept for the retry so a 300 never lands twice, a refusal shown on its line, and the active categories the editor links a line to

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
// A namespace import read at call time, not named imports: other suites mock
// `@/lib/api` with a fixed list of names, and a named import of one they do not
// list would fail to link for every screen that renders the day.
import * as api from '@/lib/api';
import type { PlanFacting } from '@/components/day/PlanSections';
import type {
  Category,
  PlanFactDraft,
  PlanFactWrite,
  PlanItemFacts,
  PlanItemPatch,
} from '@/lib/api';
import { factErrorText, newFactKey } from '@/lib/plan-facts';

/** The four calls the plan card makes; a parameter so tests need no module mock. */
export interface PlanFactsClient {
  record: (
    date: string,
    itemId: string,
    draft: PlanFactDraft,
    idempotencyKey: string
  ) => Promise<PlanFactWrite>;
  correct: (
    date: string,
    itemId: string,
    entryId: number,
    draft: PlanFactDraft
  ) => Promise<PlanFactWrite>;
  remove: (date: string, itemId: string, entryId: number) => Promise<PlanFactWrite>;
  categories: () => Promise<Category[]>;
}

const API_CLIENT: PlanFactsClient = {
  record: (date, itemId, draft, key) =>
    api.planFactsAPI.record(date, itemId, draft, key),
  correct: (date, itemId, entryId, draft) =>
    api.planFactsAPI.correct(date, itemId, entryId, draft),
  remove: (date, itemId, entryId) => api.planFactsAPI.remove(date, itemId, entryId),
  categories: () => api.categoriesAPI.getAll(),
};

export interface UsePlanFactsResult {
  /** Facts of every linked line, by item id. */
  byItem: Map<string, PlanItemFacts>;
  /** Active categories, for the editor that links a line to one. */
  categories: Category[];
  /** Lines with a write in flight; their inputs lock. */
  saving: Set<string>;
  /** The last refusal of each line, worded for the card. */
  errors: Map<string, string>;
  record: (itemId: string, draft: PlanFactDraft) => Promise<boolean>;
  correct: (itemId: string, entryId: number, draft: PlanFactDraft) => Promise<boolean>;
  remove: (itemId: string, entryId: number) => Promise<boolean>;
}

/** The server answered: a status means the request arrived, whatever it said. */
function answered(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'status' in error;
}

function byItemId(facts: PlanItemFacts[]): Map<string, PlanItemFacts> {
  return new Map(facts.map((one) => [one.item_id, one]));
}

/**
 * The facts of the day's linked lines, and the three writes on them.
 *
 * `onWritten` re-reads the day after a write: the mark that came with the fact
 * and the counts in the header are the server's to recount, exactly as after a
 * tick. The card itself does not wait for that — it is drawn from the write's
 * own answer.
 */
export function usePlanFacts(
  date: string,
  initial: PlanItemFacts[],
  onWritten: () => void,
  client: PlanFactsClient = API_CLIENT
): UsePlanFactsResult {
  const [byItem, setByItem] = useState(() => byItemId(initial));
  const [saving, setSaving] = useState<Set<string>>(() => new Set());
  const [errors, setErrors] = useState<Map<string, string>>(() => new Map());
  const [categories, setCategories] = useState<Category[]>([]);
  // The key of a `record` whose answer never came, by line. Sent again on the
  // next attempt: the first one may have landed, and the same key is what
  // makes the server answer with that entry instead of writing a second.
  const pendingKeys = useRef(new Map<string, string>());

  // A re-read day is the new truth. Compared by content rather than by the
  // array's identity, which changes on every render of a loading screen.
  const signature = useMemo(() => JSON.stringify(initial), [initial]);
  useEffect(() => {
    setByItem(byItemId(initial));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `signature` stands for `initial`
  }, [date, signature]);

  useEffect(() => {
    let alive = true;
    client
      .categories()
      .then((loaded) => {
        if (alive) setCategories(loaded);
      })
      .catch(() => {
        // Without the list the editor offers no link; the plan and the facts
        // already written are unaffected, so there is nothing to show here.
        if (alive) setCategories([]);
      });
    return () => {
      alive = false;
    };
  }, [client]);

  const settle = useCallback((itemId: string, error: string | null) => {
    setErrors((current) => {
      const next = new Map(current);
      if (error === null) next.delete(itemId);
      else next.set(itemId, error);
      return next;
    });
    setSaving((current) => {
      const next = new Set(current);
      next.delete(itemId);
      return next;
    });
  }, []);

  const run = useCallback(
    async (itemId: string, call: () => Promise<PlanFactWrite>): Promise<boolean> => {
      setSaving((current) => new Set(current).add(itemId));
      try {
        const answer = await call();
        pendingKeys.current.delete(itemId);
        setByItem((current) => {
          const next = new Map(current);
          if (answer.facts === null) next.delete(itemId);
          else next.set(itemId, answer.facts);
          return next;
        });
        settle(itemId, null);
        onWritten();
        return true;
      } catch (error) {
        if (answered(error)) pendingKeys.current.delete(itemId);
        settle(itemId, factErrorText(error));
        return false;
      }
    },
    [onWritten, settle]
  );

  const record = useCallback(
    (itemId: string, draft: PlanFactDraft) => {
      if (saving.has(itemId)) return Promise.resolve(false);
      const key = pendingKeys.current.get(itemId) ?? newFactKey();
      pendingKeys.current.set(itemId, key);
      return run(itemId, () => client.record(date, itemId, draft, key));
    },
    [client, date, run, saving]
  );

  const correct = useCallback(
    (itemId: string, entryId: number, draft: PlanFactDraft) => {
      if (saving.has(itemId)) return Promise.resolve(false);
      return run(itemId, () => client.correct(date, itemId, entryId, draft));
    },
    [client, date, run, saving]
  );

  const remove = useCallback(
    (itemId: string, entryId: number) => {
      if (saving.has(itemId)) return Promise.resolve(false);
      return run(itemId, () => client.remove(date, itemId, entryId));
    },
    [client, date, run, saving]
  );

  return { byItem, categories, saving, errors, record, correct, remove };
}

/** The hook's state in the shape `PlanSections` draws its fact cards from. */
export function asPlanFacting(facts: UsePlanFactsResult): PlanFacting {
  return {
    byItem: facts.byItem,
    categories: facts.categories,
    saving: facts.saving,
    errors: facts.errors,
    onRecord: (itemId, draft) => void facts.record(itemId, draft),
    onCorrect: (itemId, entryId, draft) => void facts.correct(itemId, entryId, draft),
    onRemove: (itemId, entryId) => void facts.remove(itemId, entryId),
  };
}

/**
 * The editor's save, followed by a re-read of the day when the link changed.
 *
 * The card of a newly linked line is drawn from the day's `plan_facts`, which
 * the edit's own answer does not carry; any other edit needs no re-read.
 */
export function saveThenReadLink(
  edit: (itemId: string, patch: PlanItemPatch) => Promise<boolean>,
  reload: () => void
): (itemId: string, patch: PlanItemPatch) => void {
  return (itemId, patch) => {
    void edit(itemId, patch).then((saved) => {
      if (saved && 'category_id' in patch) reload();
    });
  };
}
