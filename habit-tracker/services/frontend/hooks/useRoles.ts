'use client';
// [review:need-review] PHASE-03/134, PHASE-03/135, #311
// summary: role-screen state for both shells — one read of the day (distribution of minutes plus its acts), and two writes that re-read it, because a new record changes every share on the screen and not only its own row; #135 adds the confirm of an automatic record, which is a write like any other and re-reads the day the same way

// summary: #311 — the day and the directory are one key of the shared read cache: a re-visit draws them at once, and the re-read after a write keeps the screen instead of a spinner
import { useCallback, useState } from 'react';
import {
  rolesAPI,
  type Role,
  type RoleActDraft,
  type RoleDay,
  type RoleTimeBlockDraft,
} from '@/lib/api';
import { errorMessage, useQuery } from '@/lib/query-cache';
import { LOAD_ROLES_ERROR } from '@/lib/role-format';

const NO_ROLES: Role[] = [];

/** The day and the directory, read side by side. */
async function readRoles(): Promise<{ day: RoleDay; roles: Role[] }> {
  const [day, roles] = await Promise.all([rolesAPI.day(), rolesAPI.listRoles()]);
  return { day, roles };
}

/** Everything a role screen needs; the two shells differ only in markup. */
export interface UseRolesResult {
  /** The day, or null while loading and after a failure. */
  day: RoleDay | null;
  /** The directory, for the role pickers of the two forms. */
  roles: Role[];
  loading: boolean;
  /** Set while a form is being submitted; both forms share it. */
  saving: boolean;
  error: string | null;
  addTimeBlock: (draft: RoleTimeBlockDraft) => Promise<void>;
  addAct: (draft: RoleActDraft) => Promise<void>;
  deleteTimeBlock: (id: number) => Promise<void>;
  /** Подтвердить автоматическую запись: разметка её больше не трогает. */
  confirmTimeBlock: (id: number) => Promise<void>;
}

/**
 * The roles of one day.
 *
 * Every write re-reads the whole day rather than pushing the new row into the
 * state it already has. Ninety minutes on hiring is not a fact about hiring
 * alone — it moves the share of every other role in the same paint, and a
 * patched-in row would leave three of four numbers telling yesterday's story.
 *
 * The date is left to the server. `/roles` asks for «today» without saying
 * which day that is, because the day runs from 04:00 and the browser's calendar
 * is not entitled to an opinion about it.
 */
export function useRoles(): UseRolesResult {
  const { state, refresh } = useQuery('roles', readRoles);
  const [saving, setSaving] = useState(false);
  // A refused write; the load's own failure comes from the cache.
  const [reported, setReported] = useState<string | null>(null);

  /** Run one write, then re-read the day. Errors surface, nothing is swallowed. */
  const write = useCallback(
    async (act: () => Promise<unknown>) => {
      setSaving(true);
      setReported(null);
      try {
        await act();
        await refresh();
      } catch (err) {
        setReported(err instanceof Error ? err.message : LOAD_ROLES_ERROR);
      } finally {
        setSaving(false);
      }
    },
    [refresh]
  );

  const addTimeBlock = useCallback(
    (draft: RoleTimeBlockDraft) => write(() => rolesAPI.addTimeBlock(draft)),
    [write]
  );

  const addAct = useCallback(
    (draft: RoleActDraft) => write(() => rolesAPI.addAct(draft)),
    [write]
  );

  const deleteTimeBlock = useCallback(
    (id: number) => write(() => rolesAPI.deleteTimeBlock(id)),
    [write]
  );

  const confirmTimeBlock = useCallback(
    (id: number) => write(() => rolesAPI.confirmTimeBlock(id)),
    [write]
  );

  return {
    day: state.status === 'ready' ? state.data.day : null,
    roles: state.status === 'ready' ? state.data.roles : NO_ROLES,
    loading: state.status === 'loading',
    saving,
    error: reported ?? (state.status === 'error' ? errorMessage(state, LOAD_ROLES_ERROR) : null),
    addTimeBlock,
    addAct,
    deleteTimeBlock,
    confirmTimeBlock,
  };
}
