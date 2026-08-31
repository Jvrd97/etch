'use client';
// [review:need-review] PHASE-03/140
// summary: the role directory as a screen that is not about roles needs it — one read, no loading state and no error banner, because the plan is readable and editable without it and an empty list simply means the two optional pickers are not offered

import { useEffect, useState } from 'react';
import { rolesAPI, type Role } from '@/lib/api';

/**
 * The role directory, for a screen whose subject is something else.
 *
 * `useRoles` loads the directory *and* the day and reports both states, because
 * `/roles` cannot draw anything without them. The day screen can: the plan, its
 * marks and its editor all work with no directory at all, and the only thing
 * that depends on it is whether a line offers to name a role.
 *
 * So there is neither a loading flag nor an error banner here. A failed read
 * leaves the list empty, `PlanSections` draws exactly the plan it drew before
 * `#140`, and nothing on the day screen tells a person about a request they did
 * not make. The failure is not swallowed silently: it goes to the console,
 * where the request that failed is already visible in the network log.
 */
export function useRoleDirectory(): Role[] {
  const [roles, setRoles] = useState<Role[]>([]);

  useEffect(() => {
    // The screen may unmount while the request is in flight; without this its
    // result would be written into a component that no longer exists.
    let cancelled = false;

    const load = async () => {
      try {
        const directory = await rolesAPI.listRoles();
        if (!cancelled) setRoles(directory);
      } catch (error) {
        console.warn('справочник ролей не приехал, поля роли не показываем', error);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return roles;
}
