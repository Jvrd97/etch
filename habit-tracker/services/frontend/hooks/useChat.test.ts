// [review:need-review] PHASE-03/118, PHASE-03/116, PHASE-03/189
// summary: PHASE-03/116 adds the refusals — a busy dialogue answered 409 keeps the feed readable, an exhausted slot ceiling carries its machine code, a stored turn left `streaming` locks the field until reset clears it; tests for the chat state both shells share — a half-written reply survives the screen being torn down and mounted again (the app backgrounded on a phone), a successful send leaves the draft empty on screen and in storage, the link's conversation wins over "the latest one", and a turn is not startable twice

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { DraftStorage } from '@/lib/chat-draft';

let listConversations: ReturnType<typeof mock>;
let createConversation: ReturnType<typeof mock>;
let getConversation: ReturnType<typeof mock>;
let streamMessage: ReturnType<typeof mock>;
let resetConversation: ReturnType<typeof mock>;

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
    get: (id: number) => getConversation(id),
    reset: (id: number) => resetConversation(id),
    streamMessage: (id: number, content: string, onEvent: unknown) =>
      streamMessage(id, content, onEvent),
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

const { useChat, TURN_IN_FLIGHT } = await import('./useChat');
const { chatDraftKey } = await import('@/lib/chat-draft');

const CONVERSATION = 5;
const LATEST_CONVERSATION = 9;
const HALF_WRITTEN = 'сегодня сорвалась тренировка, потому что';

/** In-memory stand-in for localStorage that outlives a mount, as the real one does. */
function fakeStorage(): DraftStorage & { map: Map<string, string> } {
  const map = new Map<string, string>();
  return {
    map,
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => {
      map.set(key, value);
    },
    removeItem: (key) => {
      map.delete(key);
    },
  };
}

function detail(id: number, messages: unknown[] = []) {
  return { id, started_on: '2026-08-03', kind: 'general', messages };
}

beforeEach(() => {
  listConversations = mock(() => Promise.resolve([{ id: LATEST_CONVERSATION }]));
  createConversation = mock(() => Promise.resolve({ id: LATEST_CONVERSATION }));
  getConversation = mock((id: number) => Promise.resolve(detail(id)));
  streamMessage = mock(() => Promise.resolve(undefined));
  resetConversation = mock(() => Promise.resolve({ reset: 1 }));
});

afterEach(cleanup);

/** Mount the hook and wait until it has a conversation. */
async function mountChat(storage: DraftStorage, conversationId: number | null = CONVERSATION) {
  const view = renderHook(() => useChat({ conversationId, storage }));
  await waitFor(() => expect(view.result.current.screen.status).toBe('ready'));
  return view;
}

describe('useChat: which conversation is open', () => {
  it('opens the one the link names, without asking for the feed', async () => {
    const view = await mountChat(fakeStorage());

    expect(view.result.current.screen).toEqual({
      status: 'ready',
      conversationId: CONVERSATION,
    });
    expect(listConversations).toHaveBeenCalledTimes(0);
  });

  it('falls back to the latest conversation when the link names none', async () => {
    const view = await mountChat(fakeStorage(), null);

    expect(view.result.current.screen).toEqual({
      status: 'ready',
      conversationId: LATEST_CONVERSATION,
    });
    expect(createConversation).toHaveBeenCalledTimes(0);
  });

  it('starts one when there is no conversation at all', async () => {
    listConversations = mock(() => Promise.resolve([]));
    const view = await mountChat(fakeStorage(), null);

    expect(createConversation).toHaveBeenCalledTimes(1);
    expect(view.result.current.screen).toEqual({
      status: 'ready',
      conversationId: LATEST_CONVERSATION,
    });
  });
});

describe('useChat: the unsent draft', () => {
  it('survives the screen being torn down and mounted again', async () => {
    // Приложение свернули посреди набранной реплики и вернулись в него: React
    // размонтировал экран, хранилище браузера осталось.
    const storage = fakeStorage();
    const first = await mountChat(storage);
    act(() => first.result.current.setDraft(HALF_WRITTEN));
    expect(storage.map.get(chatDraftKey(CONVERSATION))).toBe(HALF_WRITTEN);
    first.unmount();

    const second = await mountChat(storage);

    expect(second.result.current.draft).toBe(HALF_WRITTEN);
    expect(second.result.current.canSend).toBe(true);
  });

  it('does not hand the draft of one conversation to another', async () => {
    const storage = fakeStorage();
    const first = await mountChat(storage);
    act(() => first.result.current.setDraft(HALF_WRITTEN));
    first.unmount();

    const other = await mountChat(storage, LATEST_CONVERSATION);

    expect(other.result.current.draft).toBe('');
  });

  it('is empty on screen and in storage after a successful send', async () => {
    const storage = fakeStorage();
    const view = await mountChat(storage);
    act(() => view.result.current.setDraft(HALF_WRITTEN));

    act(() => view.result.current.send());

    await waitFor(() => expect(view.result.current.turn.phase).toBe('idle'));
    expect(streamMessage.mock.calls[0][0]).toBe(CONVERSATION);
    expect(streamMessage.mock.calls[0][1]).toBe(HALF_WRITTEN);
    expect(view.result.current.draft).toBe('');
    expect(storage.map.has(chatDraftKey(CONVERSATION))).toBe(false);
  });
});

describe('useChat: sending', () => {
  it('refuses a draft that is only whitespace', async () => {
    const view = await mountChat(fakeStorage());
    act(() => view.result.current.setDraft('   '));

    expect(view.result.current.canSend).toBe(false);
    act(() => view.result.current.send());

    expect(streamMessage).toHaveBeenCalledTimes(0);
  });

  it('does not start a second turn while one is in flight', async () => {
    // Ход, который не завершается, пока его не отпустят: ровно окно, в котором
    // второе нажатие «Отправить» и происходит.
    const release: { resolve: () => void } = { resolve: () => {} };
    streamMessage = mock(
      () =>
        new Promise<void>((resolve) => {
          release.resolve = resolve;
        })
    );
    const view = await mountChat(fakeStorage());
    act(() => view.result.current.setDraft(HALF_WRITTEN));
    act(() => view.result.current.send());

    await waitFor(() => expect(view.result.current.busy).toBe(true));
    act(() => view.result.current.setDraft('вторая реплика'));
    act(() => view.result.current.send());

    expect(streamMessage).toHaveBeenCalledTimes(1);
    expect(view.result.current.canSend).toBe(false);
    await act(async () => {
      release.resolve();
    });
  });

  it('grows the answer delta by delta instead of appearing at the end', async () => {
    streamMessage = mock(
      (_id: number, _content: string, onEvent: (event: unknown) => void) => {
        onEvent({ kind: 'delta', text: 'потому ' });
        onEvent({ kind: 'delta', text: 'что' });
        return Promise.resolve(undefined);
      }
    );
    const view = await mountChat(fakeStorage());
    act(() => view.result.current.setDraft(HALF_WRITTEN));

    act(() => view.result.current.send());

    await waitFor(() => expect(view.result.current.turn.phase).toBe('idle'));
    // Лента перечитывается с сервера после хода — строки таблицы и есть
    // разговор.
    expect(getConversation).toHaveBeenCalledTimes(2);
  });

  it('forgets the block addressed to the server when its retrieval arrives', async () => {
    /*
     * Живая лента обязана совпадать с перезагруженной.
     *
     * Сервер не кладёт заход, кончившийся блоком `need`, в сохранённое
     * сообщение (`#189`). Кадр выборки — это признак, что предыдущий текст был
     * разговором модели с сервером: он уже отражён строкой выборки под ответом,
     * и в пузыре ему делать нечего. Без сброса человек видел бы сырой JSON до
     * первой перезагрузки, а после неё — нет.
     */
    let finish: () => void = () => {};
    streamMessage = mock(
      (_id: number, _content: string, onEvent: (event: unknown) => void) =>
        new Promise<void>((resolve) => {
          finish = resolve;
          onEvent({ kind: 'delta', text: '{"need": [{"query": "streak"}]}' });
          onEvent({
            kind: 'retrieval',
            queryName: 'streak',
            rowCount: 1,
            chars: 12,
            refusal: null,
          });
          onEvent({ kind: 'delta', text: 'Серия 4 дня.' });
        })
    );
    const view = await mountChat(fakeStorage());
    act(() => view.result.current.setDraft(HALF_WRITTEN));

    act(() => view.result.current.send());

    await waitFor(() => {
      const turn = view.result.current.turn;
      expect(turn.phase === 'streaming' ? turn.text : null).toBe('Серия 4 дня.');
    });

    await act(async () => {
      finish();
    });
    await waitFor(() => expect(view.result.current.turn.phase).toBe('idle'));
  });

  it('marks the turn failed when the backend refuses it', async () => {
    streamMessage = mock(
      (_id: number, _content: string, onEvent: (event: unknown) => void) => {
        onEvent({ kind: 'error', code: 'backend_failed' });
        return Promise.resolve(undefined);
      }
    );
    const view = await mountChat(fakeStorage());
    act(() => view.result.current.setDraft(HALF_WRITTEN));

    act(() => view.result.current.send());

    await waitFor(() => expect(view.result.current.turn.phase).toBe('failed'));
    const turn = view.result.current.turn;
    expect(turn.phase === 'failed' ? turn.code : null).toBe('backend_failed');
  });
});

/** One stored message, shaped as the server sends it. */
function storedMessage(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    seq: 2,
    role: 'assistant',
    content: 'первый ',
    status: 'complete',
    error_code: null,
    input_tokens: null,
    output_tokens: null,
    cache_read_tokens: null,
    latency_ms: null,
    model: null,
    created_at: '2026-08-30T10:00:00Z',
    ...overrides,
  };
}

describe('useChat: a refused turn', () => {
  it('keeps the feed readable when the dialogue is already busy', async () => {
    // 409 — состояние диалога, а не поломка экрана: ронять ленту в «ошибка»
    // значило бы спрятать за ней и уже написанное. Отказ приходит с сервера, а
    // не от собственной блокировки: ход начали из второй вкладки, и здесь про
    // него узнают только по коду ответа.
    streamMessage = mock(() =>
      Promise.reject(new FakeAPIError(409, 'turn 3 is still running'))
    );
    let reads = 0;
    getConversation = mock((id: number) => {
      reads += 1;
      return Promise.resolve(
        reads === 1 ? detail(id) : detail(id, [storedMessage({ status: 'streaming' })])
      );
    });
    const view = await mountChat(fakeStorage());
    act(() => view.result.current.setDraft(HALF_WRITTEN));

    act(() => view.result.current.send());

    await waitFor(() => expect(view.result.current.turn.phase).toBe('failed'));
    const turn = view.result.current.turn;
    expect(turn.phase === 'failed' ? turn.code : null).toBe(TURN_IN_FLIGHT);
    expect(view.result.current.screen.status).toBe('ready');
    // Перечитанная лента показывает ту самую строку, из-за которой 409.
    await waitFor(() => expect(view.result.current.stuck).toBe(true));
  });

  it('carries the machine code when the slot ceiling is full', async () => {
    streamMessage = mock(() =>
      Promise.reject(new FakeAPIError(429, 'chat_slots_busy'))
    );
    const view = await mountChat(fakeStorage());
    act(() => view.result.current.setDraft(HALF_WRITTEN));

    act(() => view.result.current.send());

    await waitFor(() => expect(view.result.current.turn.phase).toBe('failed'));
    const turn = view.result.current.turn;
    expect(turn.phase === 'failed' ? turn.code : null).toBe('chat_slots_busy');
  });

  it('shows the screen error for a failure that is not about the turn', async () => {
    streamMessage = mock(() => Promise.reject(new Error('сеть отвалилась')));
    const view = await mountChat(fakeStorage());
    act(() => view.result.current.setDraft(HALF_WRITTEN));

    act(() => view.result.current.send());

    await waitFor(() => expect(view.result.current.screen.status).toBe('failed'));
  });
});

describe('useChat: a turn nobody will close', () => {
  it('locks the field while a stored turn is still streaming', async () => {
    // Воркер умер вместе с процессом CLI: строка осталась в `streaming`, и
    // сервер ответит 409 на любую отправку. Запирать поле надо до неё.
    getConversation = mock((id: number) =>
      Promise.resolve(detail(id, [storedMessage({ status: 'streaming' })]))
    );
    const view = await mountChat(fakeStorage());
    act(() => view.result.current.setDraft(HALF_WRITTEN));

    await waitFor(() => expect(view.result.current.stuck).toBe(true));
    expect(view.result.current.busy).toBe(true);
    expect(view.result.current.canSend).toBe(false);
  });

  it('unsticks the dialogue on reset and reads it back', async () => {
    let stuck = true;
    getConversation = mock((id: number) =>
      Promise.resolve(
        detail(id, [storedMessage({ status: stuck ? 'streaming' : 'interrupted' })])
      )
    );
    resetConversation = mock((id: number) => {
      stuck = false;
      return Promise.resolve({ reset: 1, id });
    });
    const view = await mountChat(fakeStorage());
    await waitFor(() => expect(view.result.current.stuck).toBe(true));

    act(() => view.result.current.reset());

    await waitFor(() => expect(view.result.current.stuck).toBe(false));
    expect(resetConversation).toHaveBeenCalledTimes(1);
    expect(view.result.current.messages[0]?.status).toBe('interrupted');
  });
});
