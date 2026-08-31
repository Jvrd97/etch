// [review:need-review] PHASE-03/92
// summary: tests for useDayAnchors — a click ticks the anchor and moves the counter before the round trip, «неактуально» closes it the way the server counts it, the server's answer replaces the guess, a refused write is rolled back and re-thrown, and a re-read day wins over whatever the hook was holding

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook } from '@testing-library/react';
import type { DayAnchor, DayAnchors } from '@/lib/api';

let setAnchors: ReturnType<typeof mock>;

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
    setMark: () => Promise.resolve(null),
    setAnchors: (date: string, drafts: unknown) => setAnchors(date, drafts),
  },
}));

const { useDayAnchors } = await import('./useDayAnchors');

const DATE = '2026-08-31';

const anchor = (
  kind: string,
  title: string,
  ord: number,
  overrides: Partial<DayAnchor> = {}
): DayAnchor => ({
  kind,
  title,
  ord,
  counts_for_verdict: true,
  required_in_nonwork_evening: false,
  state: null,
  note: null,
  item_id: null,
  required_today: true,
  ...overrides,
});

/** The six of the catalogue, two of them already closed — the screen of 31 August. */
const payload = (): DayAnchors => ({
  day_date: DATE,
  anchors: [
    anchor('wake', 'подъём', 1, { state: 'done' }),
    anchor('sport', 'спорт', 2, { state: 'done' }),
    anchor('work_start', 'старт работы', 3),
    anchor('review', 'ревью', 4),
    anchor('bedtime', 'отбой', 5),
    anchor('relationship', 'вечер с близкими', 6),
  ],
  done: 2,
  total: 6,
  missing: ['старт работы', 'ревью', 'отбой', 'вечер с близкими'],
});

/** What the server would answer for the same write, one round trip later. */
const stored = (kind: string, state: DayAnchor['state']): DayAnchors => {
  const base = payload();
  const anchors = base.anchors.map((a) => (a.kind === kind ? { ...a, state } : a));
  const closed = (a: DayAnchor) => a.state === 'done' || a.state === 'skipped';
  return {
    ...base,
    anchors,
    done: anchors.filter(closed).length,
    missing: anchors.filter((a) => !closed(a)).map((a) => a.title),
  };
};

beforeEach(() => {
  setAnchors = mock((_date: string, drafts: { kind: string; state: DayAnchor['state'] }[]) =>
    Promise.resolve(stored(drafts[0].kind, drafts[0].state))
  );
});

afterEach(() => {
  cleanup();
});

describe('useDayAnchors', () => {
  it('ticks the anchor before the round trip', async () => {
    // Это и есть починка: раньше галочка появлялась только после того, как
    // сервер ответил и экран перечитал день целиком — до тех пор блок стоял
    // нетронутым, а потом вся страница моргала спиннером.
    let finish: (answer: DayAnchors) => void = () => {};
    setAnchors = mock(
      () =>
        new Promise<DayAnchors>((resolve) => {
          finish = resolve;
        })
    );

    const { result } = renderHook(() => useDayAnchors(DATE, payload()));

    act(() => {
      void result.current.mark('review', 'done');
    });

    const marked = result.current.payload.anchors.find((a) => a.kind === 'review');
    expect(marked?.state).toBe('done');
    expect(result.current.payload.done).toBe(3);
    expect(result.current.payload.missing).not.toContain('ревью');

    await act(async () => {
      finish(stored('review', 'done'));
    });
  });

  it('counts «неактуально» as closed, the way the server does', async () => {
    // `skipped` не опускает день: якорь, переставший быть уместным, — не
    // пропущенный. Экран обязан считать так же, иначе счётчик разойдётся с
    // вердиктом на соседней карточке.
    const { result } = renderHook(() => useDayAnchors(DATE, payload()));

    await act(async () => {
      await result.current.mark('bedtime', 'skipped');
    });

    expect(result.current.payload.done).toBe(3);
    expect(result.current.payload.missing).not.toContain('отбой');
  });

  it('names the anchor by kind rather than by position', async () => {
    const { result } = renderHook(() => useDayAnchors(DATE, payload()));

    await act(async () => {
      await result.current.mark('relationship', 'done');
    });

    expect(setAnchors).toHaveBeenCalledWith(DATE, [
      { kind: 'relationship', state: 'done' },
    ]);
  });

  it('lets the server settle the count', async () => {
    // Локальный пересчёт — зеркало серверной формулы, а не второй источник
    // истины: ответ PUT замещает догадку целиком.
    setAnchors = mock(() =>
      Promise.resolve({ ...stored('review', 'done'), done: 5, missing: [] })
    );

    const { result } = renderHook(() => useDayAnchors(DATE, payload()));

    await act(async () => {
      await result.current.mark('review', 'done');
    });

    expect(result.current.payload.done).toBe(5);
    expect(result.current.payload.missing).toEqual([]);
  });

  it('rolls the tick back when the server refuses it', async () => {
    setAnchors = mock(() => Promise.reject(new Error('503: база недоступна')));

    const { result } = renderHook(() => useDayAnchors(DATE, payload()));

    await act(async () => {
      // Проброшена наружу, а не проглочена: строка показывает ошибку сама.
      await expect(result.current.mark('review', 'done')).rejects.toThrow('503');
    });

    const rolled = result.current.payload.anchors.find((a) => a.kind === 'review');
    expect(rolled?.state).toBeNull();
    expect(result.current.payload.done).toBe(2);
    expect(result.current.payload.missing).toContain('ревью');
  });

  it('takes a re-read day over what it was holding', async () => {
    const { result, rerender } = renderHook(
      ({ initial }) => useDayAnchors(DATE, initial),
      { initialProps: { initial: payload() } }
    );

    await act(async () => {
      await result.current.mark('review', 'done');
    });

    // Тот же день, но прочитанный заново: ревью успели переставить в `failed`
    // с телефона. Сервер прав, хук — нет, и держаться за свою галочку он не
    // имеет права.
    rerender({ initial: stored('review', 'failed') });

    const fresh = result.current.payload.anchors.find((a) => a.kind === 'review');
    expect(fresh?.state).toBe('failed');
    expect(result.current.payload.missing).toContain('ревью');
  });

  it('does not re-render itself into a loop on a fresh payload object', async () => {
    // `detail.anchors` — новый объект на каждый рендер экрана. Хук ключуется
    // на содержимом, а не на ссылке; иначе экран дня зацикливается.
    const { result, rerender } = renderHook(
      ({ initial }) => useDayAnchors(DATE, initial),
      { initialProps: { initial: payload() } }
    );

    await act(async () => {
      await result.current.mark('review', 'done');
    });
    const after = result.current.payload;

    rerender({ initial: { ...payload(), anchors: payload().anchors } });

    expect(result.current.payload).toBe(after);
  });
});
