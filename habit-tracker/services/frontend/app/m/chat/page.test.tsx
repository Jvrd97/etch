// [review:need-review] PHASE-03/118
// summary: tests for the mobile chat screen — it draws the very same feed and message field the desktop screen draws (one text, one place to change it), the field lives inside the sheet whose bar and height follow the visual viewport, and the sheet's confirm is the send action rather than a "Done" that saves nothing

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';

let getConversation: ReturnType<typeof mock>;
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
