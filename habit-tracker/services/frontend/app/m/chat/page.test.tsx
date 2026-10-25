// [review:need-review] PHASE-03/118, PHASE-03/120, PHASE-03/203, PHASE-03/197
// summary: PHASE-03/197 covers deleting from the phone's history panel — another conversation goes and the open one stays, the open one goes and the screen is left on «nothing selected» with a clean address and no new conversation, an unnamed one, a failed request kept and retried, one request on a double tap, and a running answer explained on the row
// summary: PHASE-03/203 covers the history panel on the phone — opened from the button beside the field, a picked row opening its conversation by address, «Новый разговор» creating exactly one, the draft kept across the panel and across a switch and back, a failed list retried, Escape closing only the panel, and a switch mid-answer that keeps the two feeds apart
// summary: PHASE-03/120 holds the live turn on both shells at once — the model's thought named on screen while it happens, and the caret that follows the text — because the phone and the wide screen draw one feed and a regression on one of them is a regression on both
// summary: tests for the mobile chat screen — it draws the very same feed and message field the desktop screen draws (one text, one place to change it), the field lives inside the sheet whose bar and height follow the visual viewport, and the sheet's confirm is the send action rather than a "Done" that saves nothing

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import {
  THINKING_TOGGLE_TESTID,
  THINKING_WORDS_TESTID,
} from '@/components/chat/ThinkingBlock';
import { CARET_TESTID, WAITING_TESTID } from '@/components/chat/TurnLive';
import { THINKING_LABEL } from '@/lib/chat-progress';
import type { ChatStreamEvent } from '@/lib/chat-stream';

let getConversation: ReturnType<typeof mock>;
let listConversations: ReturnType<typeof mock>;
let createConversation: ReturnType<typeof mock>;
let removeConversation: ReturnType<typeof mock>;
let pushed: string[];
let replaced: string[];
let streamTurn: (onEvent: (event: ChatStreamEvent) => void) => Promise<void>;
let searchParams: URLSearchParams;

const CONVERSATION = 5;
const STORED_MESSAGE = 'вчера не добежал';

function message(id: number, role: string, content: string) {
  return {
    id,
    seq: id,
    role,
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
  usePathname: () => '/m/chat',
  useRouter: () => ({
    push: (href: string) => {
      pushed.push(href);
    },
    replace: (href: string) => {
      replaced.push(href);
    },
  }),
}));

const { default: MobileChatPage } = await import('./page');
const { default: DesktopChatPage } = await import('@/app/chat/page');
const { MESSAGE_FIELD_LABEL, SEND_LABEL } = await import('@/components/chat/ChatComposer');
const { HISTORY_LOADING, HISTORY_RETRY, NEW_CONVERSATION, NOTHING_SELECTED } = await import(
  '@/components/chat/ChatHistory'
);
const { HISTORY_SHEET_CLOSE_LABEL, HISTORY_SHEET_TITLE } = await import(
  '@/components/chat/ChatHistorySheet'
);
const { REMOVE_RUNNING_ANSWER } = await import('@/hooks/useChatHistory');

/** A conversation of the history feed, shaped as the server lists it. */
function listed(id: number, title: string) {
  return {
    id,
    title,
    started_on: '2026-08-03',
    kind: 'general',
    llm_backend: 'cli',
    context_version: 1,
    last_message_at: '2026-08-03T10:00:00Z',
    archived: false,
    created_at: '2026-08-03T09:00:00Z',
    usage: {
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      message_count: 1,
      latency_ms_median: null,
    },
  };
}

const OPEN_TITLE = 'почему не добежал';
const OTHER = 7;
const OTHER_TITLE = 'план на завтра';
const OTHER_MESSAGE = 'сделай план на завтра';
const STARTED = 11;

beforeEach(() => {
  searchParams = new URLSearchParams(`conversation=${CONVERSATION}`);
  pushed = [];
  replaced = [];
  window.localStorage.clear();
  listConversations = mock(() =>
    Promise.resolve([listed(CONVERSATION, OPEN_TITLE), listed(OTHER, OTHER_TITLE)])
  );
  createConversation = mock(() => Promise.resolve(listed(STARTED, '')));
  removeConversation = mock(() => Promise.resolve({}));
  getConversation = mock((id: number) =>
    Promise.resolve({
      id,
      messages: [
        id === OTHER ? message(2, 'user', OTHER_MESSAGE) : message(1, 'user', STORED_MESSAGE),
      ],
      // Расход (#117) и признак продолжения (#112) приехали в детальный ответ
      // после того, как этот тест был написан; десктопная оболочка читает оба.
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

describe('the mobile chat screen', () => {
  it('opens the conversation the link names', async () => {
    render(<MobileChatPage />);

    await waitFor(() => expect(getConversation).toHaveBeenCalledWith(CONVERSATION));
    expect(await screen.findByText(STORED_MESSAGE)).toBeDefined();
  });

  it('puts the message field inside the sheet that follows the keyboard', async () => {
    // Обычная страница мобильной оболочки уезжает под клавиатуру целиком; лист
    // следит за визуальным viewport, и поле ввода вместе с ним остаётся на
    // экране. Поэтому поле обязано быть внутри диалога, а не рядом с ним.
    render(<MobileChatPage />);

    const sheet = await screen.findByRole('dialog');
    expect(sheet.getAttribute('aria-label')).toBe('Chat');
    expect(within(sheet).getByLabelText(MESSAGE_FIELD_LABEL)).toBeDefined();
    expect(within(sheet).getByText(STORED_MESSAGE)).toBeDefined();
  });

  it('offers sending twice under one name, and disables both on an empty draft', async () => {
    // Кнопка в шапке листа и кнопка у поля — одно действие: у поля привычнее,
    // в шапке видно всегда. Обе названы одинаково, обе выключены, пока
    // отправлять нечего.
    render(<MobileChatPage />);

    const sheet = await screen.findByRole('dialog');
    const sendControls = within(sheet).getAllByRole('button', { name: SEND_LABEL });

    expect(sendControls).toHaveLength(2);
    for (const control of sendControls) {
      expect((control as HTMLButtonElement).disabled).toBe(true);
    }
  });
});

/** Ход, который начался и не заканчивается: ровно то окно, в котором человек ждёт. */
const THOUGHT = 'он спрашивает про сон';

function heldTurn(events: ChatStreamEvent[]) {
  return (onEvent: (event: ChatStreamEvent) => void) => {
    for (const event of events) onEvent(event);
    return new Promise<void>(() => {});
  };
}

/** Набрать вопрос и отправить его — одинаково на обеих оболочках. */
async function ask(container: HTMLElement) {
  const field = within(container).getByLabelText(MESSAGE_FIELD_LABEL);
  fireEvent.change(field, { target: { value: 'как я спал?' } });
  const send = within(container).getAllByRole('button', { name: SEND_LABEL })[0];
  await act(async () => {
    fireEvent.click(send);
  });
}

describe('a turn in flight, on both shells', () => {
  it('names what the model is doing before it has said a word — on the phone', async () => {
    streamTurn = heldTurn([
      { kind: 'thinking', index: 0, thinking: THOUGHT, thinkingTokens: null },
    ]);
    const view = render(<MobileChatPage />);
    await view.findByText(STORED_MESSAGE);

    await ask(view.container);

    // Признак жизни до первого слова и подпись, объясняющая паузу.
    expect(screen.getByTestId(WAITING_TESTID)).toBeDefined();
    expect(screen.getByTestId(THINKING_TOGGLE_TESTID).textContent).toContain(THINKING_LABEL);
    fireEvent.click(screen.getByTestId(THINKING_TOGGLE_TESTID));
    expect(screen.getByTestId(THINKING_WORDS_TESTID).textContent).toContain(THOUGHT);
  });

  it('names what the model is doing before it has said a word — on the wide screen', async () => {
    streamTurn = heldTurn([
      { kind: 'thinking', index: 0, thinking: THOUGHT, thinkingTokens: null },
    ]);
    const view = render(<DesktopChatPage />);
    await view.findByText(STORED_MESSAGE);

    await ask(view.container);

    expect(screen.getByTestId(WAITING_TESTID)).toBeDefined();
    expect(screen.getByTestId(THINKING_TOGGLE_TESTID).textContent).toContain(THINKING_LABEL);
  });

  it('swaps the waiting sign for a caret once the answer starts', async () => {
    streamTurn = heldTurn([
      { kind: 'thinking', index: 0, thinking: THOUGHT, thinkingTokens: null },
      { kind: 'writing', index: 1 },
      { kind: 'delta', text: 'В среднем 6 ч 40 мин.' },
    ]);
    const view = render(<MobileChatPage />);
    await view.findByText(STORED_MESSAGE);

    await ask(view.container);

    expect(screen.queryByTestId(WAITING_TESTID)).toBeNull();
    expect(screen.getByTestId(CARET_TESTID)).toBeDefined();
    // Мысль свернулась сама, но никуда не делась.
    expect(screen.queryByTestId(THINKING_WORDS_TESTID)).toBeNull();
    expect(screen.getByTestId(THINKING_TOGGLE_TESTID)).toBeDefined();
  });
});

describe('the two shells', () => {
  it('draw the same feed and the same message field', async () => {
    // Смысл переиспользования: правка текста подсказки или подписи поля — одна
    // правка, а не две. Тест держит именно это, а не разметку вокруг.
    const mobile = render(<MobileChatPage />);
    expect(await mobile.findByLabelText(MESSAGE_FIELD_LABEL)).toBeDefined();
    expect(await mobile.findByText(STORED_MESSAGE)).toBeDefined();
    cleanup();

    const desktop = render(<DesktopChatPage />);

    expect(await desktop.findByLabelText(MESSAGE_FIELD_LABEL)).toBeDefined();
    expect(await desktop.findByText(STORED_MESSAGE)).toBeDefined();
  });
});

/** Открыть панель истории нижней кнопкой и дождаться прочитанного списка. */
async function openHistory() {
  fireEvent.click(screen.getByRole('button', { name: HISTORY_SHEET_TITLE }));
  const panel = screen.getByRole('dialog', { name: HISTORY_SHEET_TITLE });
  await waitFor(() => expect(within(panel).queryByText(HISTORY_LOADING) === null).toBe(true));
  return panel;
}

function historyIsOpen(): boolean {
  return screen.queryByRole('dialog', { name: HISTORY_SHEET_TITLE }) !== null;
}

/** Переход, который сделал бы роутер: адрес сменился, экран перерисован. */
function navigate(view: ReturnType<typeof render>, conversationId: number) {
  searchParams = new URLSearchParams(`conversation=${conversationId}`);
  view.rerender(<MobileChatPage />);
}

function field(): HTMLTextAreaElement {
  return screen.getByLabelText(MESSAGE_FIELD_LABEL) as HTMLTextAreaElement;
}

describe('the history panel on the phone', () => {
  it('opens from the button beside the message field, without writing anything', async () => {
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);

    // Кнопка живёт в том же нижнем блоке, что и поле: лист следит за
    // клавиатурой, и кнопка поднимается над ней вместе с полем.
    const button = screen.getByRole('button', { name: HISTORY_SHEET_TITLE });
    const chat = screen.getByRole('dialog', { name: 'Chat' });
    expect(chat.contains(button)).toBe(true);
    expect(button.closest('.sticky')?.contains(field())).toBe(true);

    const panel = await openHistory();

    expect(await within(panel).findByText(OTHER_TITLE)).toBeDefined();
    expect(within(panel).getByRole('link', { current: 'page' }).textContent).toContain(
      OPEN_TITLE
    );
    expect(createConversation).not.toHaveBeenCalled();
  });

  it('opens a picked conversation by its address and closes', async () => {
    const view = render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();

    const row = await within(panel).findByRole('link', { name: new RegExp(OTHER_TITLE) });
    expect(row.getAttribute('href')).toBe(`/m/chat?conversation=${OTHER}`);
    fireEvent.click(row);
    expect(historyIsOpen()).toBe(false);

    navigate(view, OTHER);

    expect(await screen.findByText(OTHER_MESSAGE)).toBeDefined();
    expect(screen.queryByText(STORED_MESSAGE) === null).toBe(true);
  });

  it('starts exactly one conversation from «Новый разговор» and goes there', async () => {
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);

    await act(async () => {
      fireEvent.click(within(panel).getByRole('button', { name: NEW_CONVERSATION }));
    });

    expect(createConversation).toHaveBeenCalledTimes(1);
    expect(pushed).toEqual([`/m/chat?conversation=${STARTED}`]);
    expect(historyIsOpen()).toBe(false);
  });

  it('keeps the draft while the panel opens and closes, and hands focus back', async () => {
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    fireEvent.change(field(), { target: { value: 'недописанное' } });

    await openHistory();
    fireEvent.click(screen.getByRole('button', { name: HISTORY_SHEET_CLOSE_LABEL }));

    expect(historyIsOpen()).toBe(false);
    expect(field().value).toBe('недописанное');
    expect(document.activeElement?.getAttribute('aria-label')).toBe(HISTORY_SHEET_TITLE);
  });

  it('keeps the draft of the conversation left for another and gives it back on return', async () => {
    const view = render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    fireEvent.change(field(), { target: { value: 'недописанное' } });

    navigate(view, OTHER);
    await screen.findByText(OTHER_MESSAGE);
    expect(field().value).toBe('');

    // «Назад» в браузере — тот же адрес первого разговора.
    navigate(view, CONVERSATION);
    await screen.findByText(STORED_MESSAGE);

    await waitFor(() => expect(field().value).toBe('недописанное'));
  });

  it('says an empty history is empty rather than broken', async () => {
    listConversations = mock(() => Promise.resolve([]));
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);

    const panel = await openHistory();

    expect(await within(panel).findByRole('button', { name: NEW_CONVERSATION })).toBeDefined();
    expect(within(panel).queryAllByRole('link')).toHaveLength(0);
  });

  it('retries a list that failed to load', async () => {
    let reads = 0;
    listConversations = mock(() => {
      reads += 1;
      return reads === 1
        ? Promise.reject(new Error('502: бэкенд молчит'))
        : Promise.resolve([listed(OTHER, OTHER_TITLE)]);
    });
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();

    fireEvent.click(await within(panel).findByRole('button', { name: HISTORY_RETRY }));

    expect(await within(panel).findByText(OTHER_TITLE)).toBeDefined();
    expect(within(panel).queryByText(/502/) === null).toBe(true);
  });

  it('holds a long history inside its own scrolling list', async () => {
    const LONG = 40;
    listConversations = mock(() =>
      Promise.resolve(Array.from({ length: LONG }, (_, i) => listed(100 + i, `разговор ${i}`)))
    );
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();

    await within(panel).findByText('разговор 39');
    expect(within(panel).getAllByRole('link')).toHaveLength(LONG);
    // «Новый разговор» не уезжает вместе со списком.
    const start = within(panel).getByRole('button', { name: NEW_CONVERSATION });
    const list = within(panel).getAllByRole('link')[0].closest('.overflow-y-auto');
    expect(list !== null).toBe(true);
    expect(list?.contains(start)).toBe(false);
  });

  it('closes only itself on Escape, not the chat underneath', async () => {
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    await openHistory();

    fireEvent.keyDown(document.activeElement ?? document, { key: 'Escape' });

    expect(historyIsOpen()).toBe(false);
    expect(screen.getByRole('dialog', { name: 'Chat' })).toBeDefined();
    expect(pushed).toEqual([]);
  });

  it('stays reachable while an answer is streaming, and the switch keeps the feeds apart', async () => {
    const release: { resolve: () => void } = { resolve: () => {} };
    streamTurn = (onEvent) => {
      onEvent({ kind: 'delta', text: 'ответ первому разговору' });
      return new Promise<void>((resolve) => {
        release.resolve = resolve;
      });
    };
    const view = render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    await ask(view.container);
    expect(field().disabled).toBe(true);

    const button = screen.getByRole('button', { name: HISTORY_SHEET_TITLE }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    const panel = await openHistory();
    fireEvent.click(await within(panel).findByRole('link', { name: new RegExp(OTHER_TITLE) }));
    navigate(view, OTHER);
    await screen.findByText(OTHER_MESSAGE);

    await act(async () => {
      release.resolve();
    });

    expect(screen.getByText(OTHER_MESSAGE)).toBeDefined();
    expect(screen.queryByText('как я спал?') === null).toBe(true);
    expect(screen.queryByText(/ответ первому разговору/) === null).toBe(true);
    expect(screen.queryByText(STORED_MESSAGE) === null).toBe(true);
  });
});

/** Ошибка сервера в той форме, по которой её узнаёт экран: имя и числовой код. */
function serverError(status: number, message: string) {
  return Object.assign(new Error(message), { name: 'APIError', status });
}

const deleteLabel = (title: string) => `Удалить разговор «${title}»`;
const UNNAMED = 9;

/** Подтверждение, открытое у строки панели. */
function confirmationIn(panel: HTMLElement, title: string) {
  return within(panel).getByRole('group', { name: `Удалить разговор «${title}»?` });
}

describe('deleting from the history panel on the phone', () => {
  it('deletes another conversation and keeps the open one on screen', async () => {
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);
    const reads = getConversation.mock.calls.length;

    fireEvent.click(within(panel).getByRole('button', { name: deleteLabel(OTHER_TITLE) }));
    await act(async () => {
      fireEvent.click(
        within(confirmationIn(panel, OTHER_TITLE)).getByRole('button', { name: 'Удалить' })
      );
    });

    expect(removeConversation).toHaveBeenCalledTimes(1);
    expect(removeConversation).toHaveBeenCalledWith(OTHER);
    expect(within(panel).queryByText(OTHER_TITLE) === null).toBe(true);
    expect(within(panel).getByRole('link', { current: 'page' }).textContent).toContain(OPEN_TITLE);
    expect(screen.getByText(STORED_MESSAGE)).toBeDefined();
    expect(getConversation.mock.calls.length).toBe(reads);
    expect(replaced).toEqual([]);
    expect(pushed).toEqual([]);
    expect(createConversation).not.toHaveBeenCalled();
  });

  it('asks first and sends nothing when the question is cancelled', async () => {
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);

    fireEvent.click(within(panel).getByRole('button', { name: deleteLabel(OTHER_TITLE) }));
    expect(confirmationIn(panel, OTHER_TITLE).textContent).toContain('История сообщений исчезнет');
    fireEvent.click(within(confirmationIn(panel, OTHER_TITLE)).getByRole('button', { name: 'Отмена' }));

    expect(removeConversation).not.toHaveBeenCalled();
    expect(within(panel).getByText(OTHER_TITLE)).toBeDefined();
    expect(pushed).toEqual([]);
    expect(historyIsOpen()).toBe(true);
  });

  it('deletes the open conversation and leaves the screen on «nothing selected»', async () => {
    const view = render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    fireEvent.change(field(), { target: { value: 'недописанное' } });
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);

    fireEvent.click(within(panel).getByRole('button', { name: deleteLabel(OPEN_TITLE) }));
    await act(async () => {
      fireEvent.click(
        within(confirmationIn(panel, OPEN_TITLE)).getByRole('button', { name: 'Удалить' })
      );
    });
    expect(removeConversation).toHaveBeenCalledWith(CONVERSATION);
    // Адрес перестаёт называть удалённый разговор.
    expect(replaced).toEqual(['/m/chat']);
    // Роутер ещё не перешёл, ссылка пока называет удалённый разговор — а экран
    // уже не показывает его и не открывает другой.
    expect(await screen.findByText(NOTHING_SELECTED)).toBeDefined();
    expect(createConversation).not.toHaveBeenCalled();

    // Переход, который сделал бы роутер.
    searchParams = new URLSearchParams();
    view.rerender(<MobileChatPage />);

    expect(await screen.findByText(NOTHING_SELECTED)).toBeDefined();
    expect(screen.queryByText(STORED_MESSAGE) === null).toBe(true);
    expect(field().value).toBe('');
    expect(field().disabled).toBe(true);
    // Ни свежий разговор не открыт, ни новый не заведён.
    expect(createConversation).not.toHaveBeenCalled();
    expect(listConversations).not.toHaveBeenCalledWith(1);
    expect(within(panel).queryByText(OPEN_TITLE) === null).toBe(true);
    expect(within(panel).queryAllByRole('link', { current: 'page' })).toHaveLength(0);
    // Панель осталась: из неё и выбирают следующий.
    expect(historyIsOpen()).toBe(true);
  });

  it('leaves the latest conversation shown without a link just the same', async () => {
    // Из «More» чат открывается без ссылки и берёт свежий разговор. Адрес тут
    // не изменится — значит, пустой экран не может зависеть от адреса.
    searchParams = new URLSearchParams();
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);

    fireEvent.click(within(panel).getByRole('button', { name: deleteLabel(OPEN_TITLE) }));
    await act(async () => {
      fireEvent.click(
        within(confirmationIn(panel, OPEN_TITLE)).getByRole('button', { name: 'Удалить' })
      );
    });

    expect(removeConversation).toHaveBeenCalledWith(CONVERSATION);
    expect(await screen.findByText(NOTHING_SELECTED)).toBeDefined();
    expect(screen.queryByText(STORED_MESSAGE) === null).toBe(true);
    expect(createConversation).not.toHaveBeenCalled();
  });

  it('opens another conversation after the open one is gone, and only that one', async () => {
    const view = render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);
    fireEvent.click(within(panel).getByRole('button', { name: deleteLabel(OPEN_TITLE) }));
    await act(async () => {
      fireEvent.click(
        within(confirmationIn(panel, OPEN_TITLE)).getByRole('button', { name: 'Удалить' })
      );
    });
    searchParams = new URLSearchParams();
    view.rerender(<MobileChatPage />);
    await screen.findByText(NOTHING_SELECTED);

    fireEvent.click(within(panel).getByRole('link', { name: new RegExp(OTHER_TITLE) }));
    navigate(view, OTHER);

    expect(await screen.findByText(OTHER_MESSAGE)).toBeDefined();
    expect(screen.queryByText(NOTHING_SELECTED) === null).toBe(true);
    expect(createConversation).not.toHaveBeenCalled();
  });

  it('keeps the conversation opened while the delete request was running', async () => {
    // Человек нажал «Удалить» у открытого разговора и, не дожидаясь ответа,
    // открыл другой. Решает тот, что открыт в момент ответа сервера.
    let release: () => void = () => {};
    removeConversation = mock(
      () =>
        new Promise((resolve) => {
          release = () => resolve({});
        })
    );
    const view = render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);
    fireEvent.click(within(panel).getByRole('button', { name: deleteLabel(OPEN_TITLE) }));
    await act(async () => {
      fireEvent.click(
        within(confirmationIn(panel, OPEN_TITLE)).getByRole('button', { name: 'Удалить' })
      );
    });

    navigate(view, OTHER);
    await screen.findByText(OTHER_MESSAGE);
    await act(async () => {
      release();
    });

    expect(screen.getByText(OTHER_MESSAGE)).toBeDefined();
    expect(screen.queryByText(NOTHING_SELECTED) === null).toBe(true);
    expect(within(panel).queryByText(OPEN_TITLE) === null).toBe(true);
    expect(field().disabled).toBe(false);
    expect(replaced).toEqual([]);
    expect(createConversation).not.toHaveBeenCalled();
  });

  it('deletes a conversation nobody asked anything under its display name', async () => {
    listConversations = mock(() =>
      Promise.resolve([listed(CONVERSATION, OPEN_TITLE), listed(UNNAMED, '')])
    );
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText('Разговор без вопроса');

    fireEvent.click(
      within(panel).getByRole('button', { name: deleteLabel('Разговор без вопроса') })
    );
    expect(confirmationIn(panel, 'Разговор без вопроса')).toBeDefined();
    await act(async () => {
      fireEvent.click(
        within(confirmationIn(panel, 'Разговор без вопроса')).getByRole('button', {
          name: 'Удалить',
        })
      );
    });

    expect(removeConversation).toHaveBeenCalledWith(UNNAMED);
    expect(within(panel).queryByText('Разговор без вопроса') === null).toBe(true);
  });

  it('keeps the row when the request fails and deletes on the retry', async () => {
    removeConversation = mock(() => Promise.reject(new Error('500: база недоступна')));
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);
    fireEvent.click(within(panel).getByRole('button', { name: deleteLabel(OTHER_TITLE) }));
    await act(async () => {
      fireEvent.click(
        within(confirmationIn(panel, OTHER_TITLE)).getByRole('button', { name: 'Удалить' })
      );
    });

    expect(within(panel).getByRole('alert').textContent).toContain('500');
    expect(within(panel).getByText(OTHER_TITLE)).toBeDefined();

    removeConversation = mock(() => Promise.resolve({}));
    await act(async () => {
      fireEvent.click(
        within(confirmationIn(panel, OTHER_TITLE)).getByRole('button', {
          name: 'Удалить ещё раз',
        })
      );
    });

    expect(removeConversation).toHaveBeenCalledTimes(1);
    expect(within(panel).queryByText(OTHER_TITLE) === null).toBe(true);
  });

  it('sends one request on a double tap', async () => {
    let release: () => void = () => {};
    removeConversation = mock(
      () =>
        new Promise((resolve) => {
          release = () => resolve({});
        })
    );
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);
    fireEvent.click(within(panel).getByRole('button', { name: deleteLabel(OTHER_TITLE) }));
    const confirmButton = within(confirmationIn(panel, OTHER_TITLE)).getByRole('button', {
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

  it('explains on the row why the conversation with a running answer is not deletable', async () => {
    streamTurn = heldTurn([{ kind: 'delta', text: 'ответ' }]);
    const view = render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    await ask(view.container);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);

    const running = within(panel).getByRole('button', { name: deleteLabel(OPEN_TITLE) });
    expect(running.getAttribute('aria-disabled')).toBe('true');
    expect(within(panel).getByText(REMOVE_RUNNING_ANSWER)).toBeDefined();
    fireEvent.click(running);
    expect(within(panel).queryByRole('group') === null).toBe(true);
    expect(removeConversation).not.toHaveBeenCalled();
    // Другой разговор при этом удаляется: запрет только про тот, где пишут ответ.
    expect(
      within(panel).getByRole('button', { name: deleteLabel(OTHER_TITLE) }).getAttribute('aria-disabled')
    ).toBeNull();
  });

  it('relays the server refusal when the answer runs where this screen cannot see it', async () => {
    removeConversation = mock(() =>
      Promise.reject(serverError(409, 'turn 2 of conversation 7 is still running'))
    );
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);
    fireEvent.click(within(panel).getByRole('button', { name: deleteLabel(OTHER_TITLE) }));
    await act(async () => {
      fireEvent.click(
        within(confirmationIn(panel, OTHER_TITLE)).getByRole('button', { name: 'Удалить' })
      );
    });

    expect(within(panel).getByRole('alert').textContent).toBe(REMOVE_RUNNING_ANSWER);
    expect(within(panel).getByText(OTHER_TITLE)).toBeDefined();
  });

  it('puts the delete within reach of a finger and of the keyboard', async () => {
    render(<MobileChatPage />);
    await screen.findByText(STORED_MESSAGE);
    const panel = await openHistory();
    await within(panel).findByText(OTHER_TITLE);

    const button = within(panel).getByRole('button', { name: deleteLabel(OTHER_TITLE) });

    expect(button.tagName).toBe('BUTTON');
    expect(button.style.minHeight).toBe('44px');
    expect(button.style.minWidth).toBe('44px');
    expect(button.getAttribute('tabindex')).toBeNull();
    expect(panel.contains(button)).toBe(true);
  });
});
