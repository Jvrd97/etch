// [review:need-review] PHASE-03/111
// summary: tests for useChatHistory — the feed is read once and re-read on demand, a new conversation is created and lands on top without waiting for a round trip, a failed read is named rather than shown as an empty history, and creation never runs twice at once

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { DraftStorage } from '@/lib/chat-draft';

let listConversations: ReturnType<typeof mock>;
let createConversation: ReturnType<typeof mock>;

/**
 * Stand-in for the error class the API client throws.
 *
 * The module is mocked wholesale, so the class has to come from the mock too:
 * `refusalCode` narrows on `instanceof`, and a plain Error would take every
 * refusal down the "the screen is broken" path instead.
 */
class FakeAPIError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = 'APIError';
  }
}

// Declares the whole @/lib/api surface: bun fixes a module's export names the
// first time anything links against it and shares that registry across the run.
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
  // Обязательства (#127). Есть в каждом моке api по причине, названной выше.
  challengesAPI: {
    list: () => Promise.resolve([]),
    get: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    patch: () => Promise.resolve(null),
    recompute: () => Promise.resolve(null),
    setDayVerdict: () => Promise.resolve(null),
  },
  quickMarksAPI: {
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
  },
  APIError: FakeAPIError,
  chatAPI: {
    list: (limit?: number) => listConversations(limit),
    create: (options?: unknown) => createConversation(options),
    get: () => Promise.resolve(null),
    reset: () => Promise.resolve({ reset: 0 }),
    streamMessage: () => Promise.resolve(undefined),
  },
  trainingAPI: { getState: () => Promise.resolve(null) },
  dayAPI: { getToday: () => Promise.resolve(null), get: () => Promise.resolve(null) },
  dailySummaryAPI: { draft: () => Promise.resolve(null), apply: () => Promise.resolve(null) },
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
    addField: () => Promise.resolve(null),
    applyBatch: () => Promise.resolve({ categories: [], fields: [] }),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  journalAPI: { getAll: () => Promise.resolve({ total: 0, items: [] }) },
}));

const { useChatHistory } = await import('./useChatHistory');

const conversation = (id: number, overrides: Record<string, unknown> = {}) => ({
  id,
  title: `Вопрос ${id}`,
  started_on: '2026-08-31',
  kind: 'general',
  llm_backend: 'cli',
  context_version: 1,
  last_message_at: `2026-08-31T1${id}:00:00`,
  archived: false,
  created_at: '2026-08-31T09:00:00',
  usage: {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    message_count: 2,
    latency_ms_median: null,
  },
  ...overrides,
});

beforeEach(() => {
  listConversations = mock(() => Promise.resolve([conversation(2), conversation(1)]));
  createConversation = mock(() => Promise.resolve(conversation(3, { title: null })));
});

afterEach(() => {
  cleanup();
});

describe('useChatHistory', () => {
  it('reads the feed once and reports what it holds', async () => {
    const { result } = renderHook(() => useChatHistory());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(listConversations).toHaveBeenCalledTimes(1);
    expect(result.current.conversations.map((one) => one.id)).toEqual([2, 1]);
    expect(result.current.error).toBeNull();
  });

  it('puts a new conversation on top without waiting for a re-read', async () => {
    // Экран переходит на заведённый разговор сразу, и список обязан уже
    // содержать строку, на которую человек смотрит. Перечитывание ленты —
    // отдельный ход, оно приезжает после.
    const { result } = renderHook(() => useChatHistory());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const outcome: { id: number | null } = { id: null };
    await act(async () => {
      outcome.id = await result.current.start();
    });

    expect(outcome.id).toBe(3);
    expect(result.current.conversations.map((one) => one.id)).toEqual([3, 2, 1]);
  });

  it('names a failed read instead of showing an empty history', async () => {
    // Пустая история и непрочитанная — разные ответы на «где мои разговоры»,
    // и второй нельзя показывать первым.
    listConversations = mock(() => Promise.reject(new Error('502: бэкенд молчит')));

    const { result } = renderHook(() => useChatHistory());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toContain('502');
    expect(result.current.conversations).toEqual([]);
  });

  it('keeps the history when starting a conversation fails', async () => {
    createConversation = mock(() => Promise.reject(new Error('503: база недоступна')));

    const { result } = renderHook(() => useChatHistory());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const outcome: { id: number | null } = { id: 0 };
    await act(async () => {
      outcome.id = await result.current.start();
    });

    expect(outcome.id).toBeNull();
    expect(result.current.error).toContain('503');
    expect(result.current.conversations.map((one) => one.id)).toEqual([2, 1]);
  });

  it('re-reads the feed on demand', async () => {
    // После хода у разговора появляется заголовок и новое время последней
    // реплики: список без перечитывания врёт ровно про тот разговор, который
    // человек только что вёл.
    const { result } = renderHook(() => useChatHistory());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.reload());

    await waitFor(() => expect(listConversations).toHaveBeenCalledTimes(2));
  });

  it('does not start two conversations at once', async () => {
    let release: (value: unknown) => void = () => {};
    createConversation = mock(
      () =>
        new Promise((resolve) => {
          release = resolve;
        })
    );

    const { result } = renderHook(() => useChatHistory());
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      void result.current.start();
      void result.current.start();
    });
    await waitFor(() => expect(result.current.starting).toBe(true));

    expect(createConversation).toHaveBeenCalledTimes(1);

    await act(async () => {
      release(conversation(3, { title: null }));
    });
  });
});
