'use client';
// [review:need-review] PHASE-03/110
// summary: plan-editing state both day shells share — one line saved, added, deleted or moved at a time, the answer's whole plan taken as the new truth so no screen recomputes order by hand, the warnings a human's edit earned kept beside the line that earned them, and the refusal of the database shown where it happened instead of as a toast

import { useCallback, useState } from 'react';
import {
  dayAPI,
  type Plan,
  type PlanEdit,
  type PlanItemDraft,
  type PlanItemPatch,
  type PlanWarning,
} from '@/lib/api';

/** What the reader sees when an edit failed for a reason nobody spelled out. */
export const EDIT_FAILED = 'Правку сохранить не удалось.';

/** Text a line is born with; it is edited in place right after it appears. */
export const NEW_LINE_TEXT = 'Новый пункт';

/** Everything a day screen needs in order to let a person edit the plan. */
export interface UsePlanItemEditResult {
  /** The plan as the server last returned it, or null until the first edit. */
  plan: Plan | null;
  /** Rules a human's edit broke. Empty means the edit broke nothing. */
  warnings: PlanWarning[];
  /** Id of the line an edit is in flight for, so its row can say so. */
  saving: string | null;
  /** The line whose editor is open, or null. */
  openId: string | null;
  /** Open the editor on a line, or close it with `null`. */
  open: (itemId: string | null) => void;
  /** Why the last edit was refused, in the words of the rule it broke. */
  error: string | null;
  edit: (itemId: string, patch: PlanItemPatch) => Promise<boolean>;
  /** Add a line and open its editor on it; the text is a placeholder. */
  add: (sectionId: string, draft?: PlanItemDraft) => Promise<boolean>;
  remove: (itemId: string) => Promise<boolean>;
  move: (
    itemId: string,
    sectionId: string,
    position: number,
    parentId: string | null
  ) => Promise<boolean>;
  /** Forget the refusal — the reader has read it. */
  dismissError: () => void;
}

/**
 * Editing the plan of one day, line by line.
 *
 * The whole plan is kept rather than a patched copy of the old one. The server
 * renumbers a level on every move and recomputes the schedule and the overlaps
 * on every window; a screen that spliced the answer into its own array would be
 * a second implementation of `ord`, and the first divergence would show as a
 * line drawn in a place the database does not have it in.
 *
 * A refusal is state, not a toast. 422 means a rule of the canon said no — a
 * task without a criterion, a window on a free line — and the reader has to be
 * able to read it while looking at the field that caused it.
 */
export function usePlanItemEdit(date: string): UsePlanItemEditResult {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [warnings, setWarnings] = useState<PlanWarning[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  const run = useCallback(
    async (
      busyId: string,
      call: () => Promise<PlanEdit>
    ): Promise<PlanEdit | null> => {
      setSaving(busyId);
      setError(null);
      try {
        const answer = await call();
        setPlan(answer.plan);
        setWarnings(answer.warnings);
        return answer;
      } catch (err) {
        setError(refusalText(err));
        return null;
      } finally {
        setSaving(null);
      }
    },
    []
  );

  const edit = useCallback(
    async (itemId: string, patch: PlanItemPatch) => {
      const answer = await run(itemId, () =>
        dayAPI.patchPlanItem(date, itemId, patch)
      );
      // Редактор закрывается только на удавшейся правке: отказ обязан оставить
      // человека в тех же полях, где он его получил.
      if (answer !== null) setOpenId(null);
      return answer !== null;
    },
    [date, run]
  );

  const add = useCallback(
    async (sectionId: string, draft?: PlanItemDraft) => {
      const answer = await run(sectionId, () =>
        dayAPI.addPlanItem(date, sectionId, draft ?? { text_md: NEW_LINE_TEXT })
      );
      // Пустая строка без редактора — мусор в плане; открываем её сразу.
      if (answer?.item) setOpenId(answer.item.id);
      return answer !== null;
    },
    [date, run]
  );

  const remove = useCallback(
    async (itemId: string) => {
      const answer = await run(itemId, () => dayAPI.deletePlanItem(date, itemId));
      if (answer !== null) setOpenId(null);
      return answer !== null;
    },
    [date, run]
  );

  const move = useCallback(
    async (
      itemId: string,
      sectionId: string,
      position: number,
      parentId: string | null
    ) => {
      const answer = await run(itemId, () =>
        // Уровень — это секция плюс родитель, и стрелка «выше» внутри задачи не
        // имеет права поднять шаг в секцию: родитель едет с пунктом.
        dayAPI.movePlanItem(date, itemId, {
          section_id: sectionId,
          parent_id: parentId,
          position,
        })
      );
      return answer !== null;
    },
    [date, run]
  );

  const open = useCallback((itemId: string | null) => setOpenId(itemId), []);
  const dismissError = useCallback(() => setError(null), []);

  return {
    plan,
    warnings,
    saving,
    openId,
    open,
    error,
    edit,
    add,
    remove,
    move,
    dismissError,
  };
}

/**
 * The refusal in the words of the rule the server named.
 *
 * The 422 of `#87` carries `{error, message, item_code}`, and `message` is a
 * sentence of the canon — «у задачи нет критерия «сделано»». `lib/api` already
 * lifts it into `Error.message`, so all that is left here is the fallback for a
 * failure nobody phrased: a network drop has no rule behind it.
 */
export function refusalText(error: unknown): string {
  if (!(error instanceof Error)) return EDIT_FAILED;
  return error.message || EDIT_FAILED;
}
