'use client';
// [review:need-review] PHASE-03/134
// summary: role-screen state for both shells — one read of the day (distribution of minutes plus its acts), and two writes that re-read it, because a new record changes every share on the screen and not only its own row

import { useCallback, useEffect, useState } from 'react';
import {
  rolesAPI,
  type Role,
  type RoleActDraft,
  type RoleDay,
  type RoleTimeBlockDraft,
} from '@/lib/api';
import { LOAD_ROLES_ERROR } from '@/lib/role-format';

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
  const [day, setDay] = useState<RoleDay | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshCounter, setRefreshCounter] = useState(0);

  useEffect(() => {
    // The screen may unmount while the request is in flight; without this its
    // result would overwrite a newer one.
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [today, directory] = await Promise.all([
          rolesAPI.day(),
          rolesAPI.listRoles(),
        ]);
        if (cancelled) return;
        setDay(today);
        setRoles(directory);
      } catch (err) {
        if (cancelled) return;
        setDay(null);
        setError(err instanceof Error ? err.message : LOAD_ROLES_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshCounter]);

  /** Run one write, then re-read the day. Errors surface, nothing is swallowed. */
  const write = useCallback(async (act: () => Promise<unknown>) => {
    setSaving(true);
    setError(null);
    try {
      await act();
      setRefreshCounter((n) => n + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : LOAD_ROLES_ERROR);
    } finally {
      setSaving(false);
    }
  }, []);

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

  return { day, roles, loading, saving, error, addTimeBlock, addAct, deleteTimeBlock };
}
