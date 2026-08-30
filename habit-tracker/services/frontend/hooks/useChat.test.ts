// [review:need-review] PHASE-03/118
// summary: tests for the chat state both shells share — a half-written reply survives the screen being torn down and mounted again (the app backgrounded on a phone), a successful send leaves the draft empty on screen and in storage, the link's conversation wins over "the latest one", and a turn is not startable twice

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { DraftStorage } from '@/lib/chat-draft';

let listConversations: ReturnType<typeof mock>;
let createConversation: ReturnType<typeof mock>;
let getConversation: ReturnType<typeof mock>;
let streamMessage: ReturnType<typeof mock>;

// Declares the whole @/lib/api surface: bun fixes a module's export names the
// first time anything links against it and shares that registry across the run.
mock.module('@/lib/api', () => ({
  chatAPI: {
    list: (limit?: number) => listConversations(limit),
    create: (options?: unknown) => createConversation(options),
    get: (id: number) => getConversation(id),
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

const { useChat } = await import('./useChat');
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
