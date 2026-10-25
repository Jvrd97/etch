// [review:need-review] PHASE-03/197
// summary: tests for deleting from the history on the wide /chat screen — another conversation goes and the open one stays, the open one goes (from the row or from the header, by the same path) and the screen is left on «nothing selected» with a clean address and no new conversation, an unnamed one, the date group going with its last row, cancel sending nothing, one request on a double click, a failure kept and retried, and a running answer explained instead of offered for deletion

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { ChatStreamEvent } from '@/lib/chat-stream';

let getConversation: ReturnType<typeof mock>;
let listConversations: ReturnType<typeof mock>;
let createConversation: ReturnType<typeof mock>;
let removeConversation: ReturnType<typeof mock>;
let replaced: string[];
let pushed: string[];
let streamTurn: (onEvent: (event: ChatStreamEvent) => void) => Promise<void>;
let searchParams: URLSearchParams;

const OPEN = 5;
const OPEN_TITLE = 'почему не добежал';
const OTHER = 7;
const OTHER_TITLE = 'план на завтра';
const UNNAMED = 9;
const OLD = 3;
const OLD_TITLE = 'старый вопрос';
const STORED_MESSAGE = 'вчера не добежал';
const OTHER_MESSAGE = 'сделай план на завтра';
const STARTED = 11;

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
  chatAPI: {
    list: (limit?: number) => listConversations(limit),
    create: () => createConversation(),
    get: (id: number) => getConversation(id),
    reset: () => Promise.resolve({ reset: 0 }),
    context: () => Promise.resolve(null),
    remove: (id: number) => removeConversation(id),
    getPlan: () => Promise.resolve(null),
    applyPlan: () => Promise.resolve(null),
    dismissPlan: () => Promise.resolve(undefined),
    streamMessage: (
      _id: number,
      _content: string,
      onEvent: (event: ChatStreamEvent) => void
    ) => streamTurn(onEvent),
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

mock.module('next/navigation', () => ({
  useSearchParams: () => searchParams,
  useParams: () => ({}),
  usePathname: () => '/chat',
  useRouter: () => ({
    push: (href: string) => {
      pushed.push(href);
    },
    replace: (href: string) => {
      replaced.push(href);
    },
  }),
}));

const { default: ChatPage } = await import('./page');
const { MESSAGE_FIELD_LABEL, SEND_LABEL } = await import('@/components/chat/ChatComposer');
const { NOTHING_SELECTED } = await import('@/components/chat/ChatHistory');
const { REMOVE_RUNNING_ANSWER } = await import('@/hooks/useChatHistory');

function listed(id: number, title: string, startedOn = '2026-08-03') {
  return {
    id,
    title,
    started_on: startedOn,
    kind: 'general',
    llm_backend: 'cli',
    context_version: 1,
    last_message_at: `${startedOn}T10:00:00Z`,
    archived: false,
    created_at: `${startedOn}T09:00:00Z`,
    usage: {
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      message_count: 1,
      latency_ms_median: null,
    },
  };
}

function message(id: number, content: string) {
  return {
    id,
    seq: id,
    role: 'user',
    content,
    status: 'complete',
    error_code: null,
    input_tokens: null,
    output_tokens: null,
    cache_read_tokens: null,
    latency_ms: null,
    model: null,
    created_at: '2026-08-03T10:00:00Z',
  };
}

function serverError(status: number, text: string) {
  return Object.assign(new Error(text), { name: 'APIError', status });
}

beforeEach(() => {
  searchParams = new URLSearchParams(`conversation=${OPEN}`);
  replaced = [];
  pushed = [];
  window.localStorage.clear();
  listConversations = mock(() =>
    Promise.resolve([
      listed(OPEN, OPEN_TITLE),
      listed(OTHER, OTHER_TITLE),
      listed(UNNAMED, ''),
      listed(OLD, OLD_TITLE, '2026-08-02'),
    ])
  );
  createConversation = mock(() => Promise.resolve(listed(STARTED, '')));
  removeConversation = mock(() => Promise.resolve({}));
  getConversation = mock((id: number) =>
    Promise.resolve({
      id,
      messages: [id === OTHER ? message(2, OTHER_MESSAGE) : message(1, STORED_MESSAGE)],
      usage: {
        input_tokens: 0,
        output_tokens: 0,
        cache_read_tokens: 0,
        message_count: 0,
        latency_ms_median: null,
      },
      resume_ready: false,
    })
  );
  streamTurn = () => Promise.resolve(undefined);
});

afterEach(cleanup);

const rowDelete = (title: string) =>
  screen.getByRole('button', { name: `Удалить разговор «${title}»` });
const headerDelete = () => screen.getByRole('button', { name: 'Удалить разговор' });
const confirmation = (title: string) =>
  screen.getByRole('group', { name: `Удалить разговор «${title}»?` });

async function openScreen() {
  const view = render(<ChatPage />);
  await screen.findByText(STORED_MESSAGE);
  await screen.findByText(OTHER_TITLE);
  return view;
}

async function confirmRow(title: string, label = 'Удалить') {
  fireEvent.click(rowDelete(title));
  await act(async () => {
    fireEvent.click(within(confirmation(title)).getByRole('button', { name: label }));
  });
}

describe('deleting from the history on the wide screen', () => {
  it('deletes another conversation and keeps the open one on screen', async () => {
    await openScreen();
    const reads = getConversation.mock.calls.length;

    await confirmRow(OTHER_TITLE);

    expect(removeConversation).toHaveBeenCalledTimes(1);
    expect(removeConversation).toHaveBeenCalledWith(OTHER);
    expect(screen.queryByText(OTHER_TITLE) === null).toBe(true);
    expect(screen.getByRole('link', { current: 'page' }).textContent).toContain(OPEN_TITLE);
    expect(screen.getByText(STORED_MESSAGE)).toBeDefined();
    expect(getConversation.mock.calls.length).toBe(reads);
    expect(replaced).toEqual([]);
    expect(createConversation).not.toHaveBeenCalled();
  });

  it('asks first, names the row and sends nothing on cancel', async () => {
    await openScreen();

    fireEvent.click(rowDelete(OTHER_TITLE));
    expect(confirmation(OTHER_TITLE).textContent).toContain('История сообщений исчезнет');
    fireEvent.click(within(confirmation(OTHER_TITLE)).getByRole('button', { name: 'Отмена' }));

    expect(removeConversation).not.toHaveBeenCalled();
    expect(screen.getByText(OTHER_TITLE)).toBeDefined();
    expect(screen.queryByRole('group') === null).toBe(true);
  });

  it('deletes the open conversation from its row and leaves «nothing selected»', async () => {
    await openScreen();

    await confirmRow(OPEN_TITLE);

    expect(removeConversation).toHaveBeenCalledWith(OPEN);
    expect(replaced).toEqual(['/chat']);
    // Ссылка в тесте всё ещё называет удалённый разговор, как до перехода роутера.
    expect(await screen.findByText(NOTHING_SELECTED)).toBeDefined();
    expect(screen.queryByText(STORED_MESSAGE) === null).toBe(true);
    expect(screen.queryAllByRole('link', { current: 'page' })).toHaveLength(0);
    expect(screen.queryByText(OPEN_TITLE) === null).toBe(true);
    expect(createConversation).not.toHaveBeenCalled();
    expect(listConversations).not.toHaveBeenCalledWith(1);
  });

  it('stays empty once the router has cleared the address', async () => {
    const view = await openScreen();
    await confirmRow(OPEN_TITLE);

    searchParams = new URLSearchParams();
    view.rerender(<ChatPage />);

    expect(await screen.findByText(NOTHING_SELECTED)).toBeDefined();
    expect(createConversation).not.toHaveBeenCalled();
    expect(listConversations).not.toHaveBeenCalledWith(1);
    expect(screen.queryByText(STORED_MESSAGE) === null).toBe(true);
  });

  it('opens the conversation picked after a deletion, and nothing else', async () => {
    const view = await openScreen();
    await confirmRow(OPEN_TITLE);
    searchParams = new URLSearchParams();
    view.rerender(<ChatPage />);
    await screen.findByText(NOTHING_SELECTED);

    searchParams = new URLSearchParams(`conversation=${OTHER}`);
    view.rerender(<ChatPage />);

    expect(await screen.findByText(OTHER_MESSAGE)).toBeDefined();
    expect(screen.queryByText(NOTHING_SELECTED) === null).toBe(true);
    expect(createConversation).not.toHaveBeenCalled();
  });

  it('leaves the latest conversation shown without a link just the same', async () => {
    searchParams = new URLSearchParams();
    listConversations = mock((limit?: number) =>
      Promise.resolve(
        limit === 1
          ? [listed(OPEN, OPEN_TITLE)]
          : [listed(OPEN, OPEN_TITLE), listed(OTHER, OTHER_TITLE)]
      )
    );
    render(<ChatPage />);
    await screen.findByText(STORED_MESSAGE);
    await screen.findByText(OTHER_TITLE);

    await confirmRow(OPEN_TITLE);

    expect(await screen.findByText(NOTHING_SELECTED)).toBeDefined();
    expect(screen.queryByText(STORED_MESSAGE) === null).toBe(true);
    expect(createConversation).not.toHaveBeenCalled();
    expect(listConversations.mock.calls.filter(([limit]) => limit === 1)).toHaveLength(1);
  });

  it('deletes a conversation nobody asked anything under its display name', async () => {
    await openScreen();

    fireEvent.click(rowDelete('Разговор без вопроса'));
    expect(confirmation('Разговор без вопроса')).toBeDefined();
    await act(async () => {
      fireEvent.click(
        within(confirmation('Разговор без вопроса')).getByRole('button', { name: 'Удалить' })
      );
    });

    expect(removeConversation).toHaveBeenCalledWith(UNNAMED);
    expect(screen.queryByText('Разговор без вопроса') === null).toBe(true);
  });

  it('takes the date group away with its last row', async () => {
    await openScreen();
    expect(screen.getByText('2 августа 2026')).toBeDefined();

    await confirmRow(OLD_TITLE);

    expect(screen.queryByText(OLD_TITLE) === null).toBe(true);
    expect(screen.queryByText('2 августа 2026') === null).toBe(true);
    expect(screen.getByText('3 августа 2026')).toBeDefined();
  });

  it('sends one request on a double click', async () => {
    let release: () => void = () => {};
    removeConversation = mock(
      () =>
        new Promise((resolve) => {
          release = () => resolve({});
        })
    );
    await openScreen();
    fireEvent.click(rowDelete(OTHER_TITLE));
    const confirmButton = within(confirmation(OTHER_TITLE)).getByRole('button', {
      name: 'Удалить',
    });

    await act(async () => {
      fireEvent.click(confirmButton);
      fireEvent.click(confirmButton);
    });

    expect(removeConversation).toHaveBeenCalledTimes(1);
    await act(async () => {
      release();
    });
    expect(removeConversation).toHaveBeenCalledTimes(1);
  });

  it('keeps the row when the request fails and deletes on the retry', async () => {
    removeConversation = mock(() => Promise.reject(new Error('500: база недоступна')));
    await openScreen();

    await confirmRow(OTHER_TITLE);

    expect(within(confirmation(OTHER_TITLE)).getByRole('alert').textContent).toContain('500');
    expect(screen.getByText(OTHER_TITLE)).toBeDefined();
    expect(screen.getByText(STORED_MESSAGE)).toBeDefined();

    removeConversation = mock(() => Promise.resolve({}));
    await act(async () => {
      fireEvent.click(
        within(confirmation(OTHER_TITLE)).getByRole('button', { name: 'Удалить ещё раз' })
      );
    });

    expect(removeConversation).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(OTHER_TITLE) === null).toBe(true);
  });

  it('explains a running answer on the row instead of offering the delete', async () => {
    streamTurn = (onEvent) => {
      onEvent({ kind: 'delta', text: 'ответ' });
      return new Promise<void>(() => {});
    };
    const view = await openScreen();
    fireEvent.change(within(view.container).getByLabelText(MESSAGE_FIELD_LABEL), {
      target: { value: 'как я спал?' },
    });
    await act(async () => {
      fireEvent.click(within(view.container).getAllByRole('button', { name: SEND_LABEL })[0]);
    });

    const running = rowDelete(OPEN_TITLE);
    expect(running.getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByText(REMOVE_RUNNING_ANSWER)).toBeDefined();
    fireEvent.click(running);
    expect(screen.queryByRole('group') === null).toBe(true);
    // Шапка называет ту же причину, а не открывает вопрос, на который нельзя ответить «да».
    fireEvent.click(headerDelete());
    expect(screen.getAllByText(REMOVE_RUNNING_ANSWER).length).toBeGreaterThan(1);
    expect(screen.queryByRole('group') === null).toBe(true);
    expect(removeConversation).not.toHaveBeenCalled();
    expect(rowDelete(OTHER_TITLE).getAttribute('aria-disabled')).toBeNull();
  });

  it('relays the server refusal when the answer runs where this screen cannot see it', async () => {
    removeConversation = mock(() =>
      Promise.reject(serverError(409, 'turn 2 of conversation 7 is still running'))
    );
    await openScreen();

    await confirmRow(OTHER_TITLE);

    expect(within(confirmation(OTHER_TITLE)).getByRole('alert').textContent).toBe(
      REMOVE_RUNNING_ANSWER
    );
    expect(screen.getByText(OTHER_TITLE)).toBeDefined();
  });

  it('puts the delete within reach of a finger and of the keyboard', async () => {
    await openScreen();

    const button = rowDelete(OTHER_TITLE);

    expect(button.tagName).toBe('BUTTON');
    expect(button.style.minHeight).toBe('44px');
    expect(button.style.minWidth).toBe('44px');
    expect(button.getAttribute('tabindex')).toBeNull();
  });
});

describe('deleting from the header of the wide screen', () => {
  it('ends in the same «nothing selected» state as deleting from the row', async () => {
    await openScreen();

    fireEvent.click(headerDelete());
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));
    });

    expect(removeConversation).toHaveBeenCalledWith(OPEN);
    expect(replaced).toEqual(['/chat']);
    expect(await screen.findByText(NOTHING_SELECTED)).toBeDefined();
    expect(screen.queryByText(OPEN_TITLE) === null).toBe(true);
    expect(createConversation).not.toHaveBeenCalled();
  });

  it('keeps the conversation and offers a retry when the request fails', async () => {
    removeConversation = mock(() => Promise.reject(new Error('500: база недоступна')));
    await openScreen();

    fireEvent.click(headerDelete());
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));
    });

    expect(screen.getByRole('alert').textContent).toContain('500');
    expect(screen.getByText(STORED_MESSAGE)).toBeDefined();
    expect(screen.getByText(OPEN_TITLE)).toBeDefined();

    removeConversation = mock(() => Promise.resolve({}));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));
    });
    expect(removeConversation).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(NOTHING_SELECTED)).toBeDefined();
  });
});
