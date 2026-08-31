// [review:need-review] PHASE-03/118, PHASE-03/120
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
    list: () => Promise.resolve([{ id: CONVERSATION }]),
    create: () => Promise.resolve({ id: CONVERSATION }),
    get: (id: number) => getConversation(id),
    reset: () => Promise.resolve({ reset: 0 }),
    context: () => Promise.resolve(null),
    remove: () => Promise.resolve({}),
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
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

const { default: MobileChatPage } = await import('./page');
const { default: DesktopChatPage } = await import('@/app/chat/page');
const { MESSAGE_FIELD_LABEL, SEND_LABEL } = await import('@/components/chat/ChatComposer');

beforeEach(() => {
  searchParams = new URLSearchParams(`conversation=${CONVERSATION}`);
  getConversation = mock((id: number) =>
    Promise.resolve({
      id,
      messages: [message(1, 'user', STORED_MESSAGE)],
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
