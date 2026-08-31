// [review:need-review] PHASE-03/88
// summary: tests for useDayMarks — a click sends an explicit state rather than "the next one", the header counts before the round trip and leaves `skipped` out of both columns, a refused write is rolled back, and a note is never written onto a line with no mark

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { Mark } from '@/lib/api';

let setMark: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export *names*
// the first time anything links against it and shares that registry across the
// run, so a partial mock here would delete members other suites reach for.
mock.module('@/lib/api', () => ({
  // Профили потолка и долг за переработку (#179): экран дня читает предложение,
  // экран недели — гроссбух. Заглушка стоит в каждом моке api, потому что bun
  // фиксирует имена экспортов модуля при первой линковке.
  profilesAPI: {
    proposal: () => Promise.resolve(null),
    activate: () => Promise.resolve(null),
    decline: () => Promise.resolve(null),
    debt: () => Promise.resolve({ open_minutes: 0, debts: [] }),
  },
  // Активность агента (#158, #160): экран дня читает её ради блока «где прошёл
  // день», а bun фиксирует имена экспортов модуля при первой линковке — мок,
  // забывший экспорт, удаляет его для всех, кто линкуется следом.
  agentAPI: {
    day: () => Promise.resolve(null),
    patchInterval: () => Promise.resolve(null),
    addManualInterval: () => Promise.resolve(null),
    titleRules: () => Promise.resolve([]),
    addTitleRule: () => Promise.resolve([]),
    patchTitleRule: () => Promise.resolve([]),
    deleteTitleRule: () => Promise.resolve([]),
    reorderTitleRules: () => Promise.resolve([]),
    settings: () => Promise.resolve({ titles_enabled: true, sampling_seconds: 5 }),
    saveSettings: () => Promise.resolve({ titles_enabled: true, sampling_seconds: 5 }),
  },
  // Справочник ролей (#140): экран дня читает его ради двух необязательных
  // полей у пункта плана. Заглушка стоит в каждом моке api по той же причине,
  // что и остальная поверхность: bun фиксирует имена экспортов модуля при
  // первой линковке, и мок, забывший экспорт, удаляет его для всех, кто
  // линкуется следом.
  rolesAPI: {
    listRoles: () => Promise.resolve([]),
    day: () => Promise.resolve(null),
    addTimeBlock: () => Promise.resolve(null),
    deleteTimeBlock: () => Promise.resolve({}),
    addAct: () => Promise.resolve(null),
    deleteAct: () => Promise.resolve({}),
  },
  // Правила дня (#152). Есть в каждом моке api по той же причине, что и
  // остальная поверхность: bun фиксирует имена экспортов модуля при первой
  // линковке, и мок, забывший экспорт, удаляет его для всех, кто линкуется следом.
  dayRulesAPI: {
    getHistory: () => Promise.resolve(null),
    getCurrent: () => Promise.resolve(null),
    publish: () => Promise.resolve(null),
  },
  // The goal board's client (#93). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  goalsAPI: {
    get: () => Promise.resolve(null),
    patchMilestone: () => Promise.resolve(null),
  },
  // The quick-mark directory and its one write path (#121). Present in every
  // api mock for the reason named above: bun fixes a module's export names on
  // first link, so a mock that omits an export deletes it for whoever links next.
  quickMarksAPI: {
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
    undo: () => Promise.resolve(null),
    sources: () => Promise.resolve([]),
  },
  // The Today screen carries the challenge block (#127). Present in every api
  // mock for the same reason the rest of the surface is: bun fixes a module's
  // export names on first link, so a mock that omits it deletes it for whoever
  // runs next.
  challengesAPI: {
    list: () => Promise.resolve([]),
    get: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    patch: () => Promise.resolve(null),
    recompute: () => Promise.resolve(null),
  },
  chatAPI: {
    list: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
    streamMessage: () => Promise.resolve(undefined),
  },
  // The training client (#92). Present in every api mock for the same reason
  // the rest of the surface is: bun fixes a module's export names on first
  // link, so a mock that omits it deletes it for whoever runs next.
  trainingAPI: { getState: () => Promise.resolve(null) },
  dailySummaryAPI: {
    draft: () => Promise.resolve({ metrics: [], unresolved: [] }),
    apply: () => Promise.resolve({ entry_ids: [] }),
  },
  onboardingAPI: { draft: () => Promise.resolve({ operations: [] }) },
  insightsAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  categoriesAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  journalAPI: {
    getAll: () => Promise.resolve({ items: [], total: 0 }),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  dayAPI: {
    getToday: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
    openToday: () => Promise.resolve(null),
    open: () => Promise.resolve(null),
    savePlan: () => Promise.resolve(null),
    saveNotebook: () => Promise.resolve({ content: '' }),
    setMark: (date: string, itemId: string, draft: unknown) =>
      setMark(date, itemId, draft),
  },
}));

const { useDayMarks } = await import('./useDayMarks');

const DATE = '2026-08-31';

/** Three tasks and an anchor: the anchor must stay out of the count. */
const KINDS = new Map<string, string>([
  ['t1', 'task'],
  ['t2', 'task'],
  ['t3', 'task'],
  ['a1', 'anchor'],
]);

const stored = (itemId: string, overrides: Partial<Mark> = {}): Mark => ({
  item_id: itemId,
  state: 'done',
  note: null,
  marked_at: '2026-08-31T09:00:00Z',
  updated_at: '2026-08-31T09:00:00Z',
  source: 'web',
  ...overrides,
});

beforeEach(() => {
  setMark = mock((_date: string, itemId: string, draft: { state: Mark['state'] }) =>
    Promise.resolve(
      draft.state === null ? stored(itemId, { state: null }) : stored(itemId, draft)
    )
  );
});

afterEach(() => {
  cleanup();
});

describe('useDayMarks', () => {
  it('sends the state it wants, not the step it is taking', async () => {
    // Two tabs asking for "the next one" would get a result that depends on
    // which arrived first; naming the state makes the last writer the winner.
    const { result } = renderHook(() => useDayMarks(DATE, [], KINDS));

    act(() => result.current.cycle('t1'));
    await waitFor(() => expect(setMark).toHaveBeenCalled());

    expect(setMark).toHaveBeenCalledWith(DATE, 't1', { state: 'done', note: null });
  });

  it('walks the ring from whatever the line already is', async () => {
    const { result } = renderHook(() =>
      useDayMarks(DATE, [stored('t1', { state: 'done' })], KINDS)
    );

    act(() => result.current.cycle('t1'));
    await waitFor(() => expect(setMark).toHaveBeenCalled());
    expect(setMark).toHaveBeenLastCalledWith(DATE, 't1', {
      state: 'failed',
      note: null,
    });

    act(() => result.current.cycle('t1'));
    await waitFor(() => expect(setMark).toHaveBeenCalledTimes(2));
    expect(setMark).toHaveBeenLastCalledWith(DATE, 't1', {
      state: null,
      note: null,
    });
  });

  it('counts tasks as the click happens, not a round trip later', async () => {
    const { result } = renderHook(() => useDayMarks(DATE, [], KINDS));

    expect(result.current.counts).toEqual({
      planned: 3,
      done: 0,
      failed: 0,
      skipped: 0,
      pending: 3,
    });

    act(() => result.current.cycle('t1'));

    await waitFor(() => expect(result.current.counts.done).toBe(1));
    expect(result.current.counts.pending).toBe(2);
  });

  it('leaves a skipped task out of both closed and failed', async () => {
    const { result } = renderHook(() => useDayMarks(DATE, [], KINDS));

    act(() => result.current.setState('t1', 'skipped'));

    await waitFor(() => expect(result.current.counts.skipped).toBe(1));
    expect(result.current.counts.done).toBe(0);
    expect(result.current.counts.failed).toBe(0);
    expect(result.current.counts.planned).toBe(3);
  });

  it('rolls the click back when the server refuses it', async () => {
    // A tick that stayed on screen after the write failed is exactly the lie
    // the file-backed page told.
    setMark = mock(() => Promise.reject(new Error('404: нет такого пункта')));
    const { result } = renderHook(() => useDayMarks(DATE, [], KINDS));

    act(() => result.current.cycle('t1'));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.marks.get('t1')).toBeUndefined();
    expect(result.current.counts.done).toBe(0);
  });

  it('writes a note without moving the state', async () => {
    const { result } = renderHook(() =>
      useDayMarks(DATE, [stored('t1', { state: 'failed' })], KINDS)
    );

    act(() => result.current.setNote('t1', 'не хватило часа'));

    await waitFor(() => expect(setMark).toHaveBeenCalled());
    expect(setMark).toHaveBeenCalledWith(DATE, 't1', {
      state: 'failed',
      note: 'не хватило часа',
    });
  });

  it('refuses to write a note onto a line with no mark', () => {
    // The note lives on the mark row; there is nowhere to put one without a
    // state, and inventing `done` would tick a line the person never ticked.
    const { result } = renderHook(() => useDayMarks(DATE, [], KINDS));

    act(() => result.current.setNote('t1', 'что-то'));

    expect(setMark).not.toHaveBeenCalled();
  });
});
