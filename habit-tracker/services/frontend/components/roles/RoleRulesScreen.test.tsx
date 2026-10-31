// [review:need-review] PHASE-03/264
// summary: tests for RoleRulesScreen — the re-markup range ends on the work day the server named (GET /roles/day), thirty days wide, whatever the browser's clock says

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
// A namespace read at call time, as the screen reads it.
import * as api from '@/lib/api';
import type { RoleDay } from '@/lib/api';
import { replaceMethod } from '@/test-fixtures/replace-method';
import RoleRulesScreen from './RoleRulesScreen';

// A day no browser clock in this run can be on.
const WORK_DAY = '2031-03-05';
const RANGE_START = '2031-02-04';

const restores: (() => void)[] = [];

beforeEach(() => {
  restores.push(
    replaceMethod(api.rolesAPI, 'listRoles', mock(() => Promise.resolve([]))),
    replaceMethod(api.rolesAPI, 'listRules', mock(() => Promise.resolve([]))),
    replaceMethod(api.rolesAPI, 'day', mock(() => Promise.resolve({ work_day: WORK_DAY } as RoleDay)))
  );
});

afterEach(() => {
  cleanup();
  for (const restore of restores.splice(0)) restore();
});

describe('RoleRulesScreen', () => {
  it('ends the re-markup range on the work day of the server', async () => {
    render(<RoleRulesScreen />);

    await waitFor(() => expect(screen.getByLabelText('По')).toBeTruthy());
    expect((screen.getByLabelText('По') as HTMLInputElement).value).toBe(WORK_DAY);
    expect((screen.getByLabelText('С') as HTMLInputElement).value).toBe(RANGE_START);
  });
});
