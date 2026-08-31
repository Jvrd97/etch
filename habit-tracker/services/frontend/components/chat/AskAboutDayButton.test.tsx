// [review:need-review] PHASE-03/118
// summary: tests for the "ask about the day" entry point — the conversation carries the date of the screen and not the server's today, it opens in the shell the button was pressed in, and a refused request leaves the reader on Today with the reason instead of on a chat that does not exist

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

let createConversation: ReturnType<typeof mock>;
let pushed: string[];
let pathname: string;

// Declares the whole @/lib/api surface: bun fixes a module's export names the
// first time anything links against it and shares that registry across the run.
mock.module('@/lib/api', () => ({
  quickMarksAPI: {
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
  },
  chatAPI: {
    list: () => Promise.resolve([]),
    create: (options?: unknown) => createConversation(options),
    get: () => Promise.resolve(null),
    streamMessage: () => Promise.resolve(undefined),
  },
  trainingAPI: { getState: () => Promise.resolve(null) },
  dayAPI: {
    getToday: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
  },
  dailySummaryAPI: {
    draft: () => Promise.resolve(null),
    apply: () => Promise.resolve(null),
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
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  usePathname: () => pathname,
  useRouter: () => ({
    push: (href: string) => {
      pushed.push(href);
    },
    replace: () => {},
  }),
}));

const { default: AskAboutDayButton, ASK_ABOUT_DAY_LABEL } = await import(
  './AskAboutDayButton'
);

/** The day the screen is showing. Deliberately not today. */
const SCREEN_DATE = '2026-08-03';
const CONVERSATION_ID = 17;

beforeEach(() => {
  pushed = [];
  pathname = '/today';
  createConversation = mock(() => Promise.resolve({ id: CONVERSATION_ID }));
});

afterEach(cleanup);

function press() {
  fireEvent.click(screen.getByRole('button', { name: ASK_ABOUT_DAY_LABEL }));
}

describe('AskAboutDayButton', () => {
  it('starts the conversation on the date of the screen, not on today', async () => {
    const errors: string[] = [];
    render(
      <AskAboutDayButton date={SCREEN_DATE} onError={(message) => errors.push(message)} />
    );

    press();

    await waitFor(() => expect(createConversation).toHaveBeenCalledTimes(1));
    expect(createConversation.mock.calls[0][0]).toEqual({
      started_on: SCREEN_DATE,
      kind: 'general',
    });
    // Без явной даты сервер поставил бы своё сегодня — ровно то, чего этот
    // тест не разрешает.
    const today = new Date().toISOString().slice(0, SCREEN_DATE.length);
    expect(createConversation.mock.calls[0][0].started_on).not.toBe(today);
    expect(errors).toEqual([]);
  });

  it('opens the conversation it just created, by id', async () => {
    render(<AskAboutDayButton date={SCREEN_DATE} onError={() => {}} />);

    press();

    await waitFor(() => expect(pushed).toEqual([`/chat?conversation=${CONVERSATION_ID}`]));
  });

  it('keeps a reader of the mobile shell in the mobile shell', async () => {
    pathname = '/m/today';
    render(<AskAboutDayButton date={SCREEN_DATE} onError={() => {}} />);

    press();

    await waitFor(() => expect(pushed).toEqual([`/m/chat?conversation=${CONVERSATION_ID}`]));
  });

  it('reports a refused request and goes nowhere', async () => {
    createConversation = mock(() => Promise.reject(new Error('Chat is disabled')));
    const errors: string[] = [];
    render(
      <AskAboutDayButton date={SCREEN_DATE} onError={(message) => errors.push(message)} />
    );

    press();

    await waitFor(() => expect(errors).toEqual(['Chat is disabled']));
    expect(pushed).toEqual([]);
    // Кнопка снова нажимаема: отказ бэкенда — не конец экрана.
    const button = screen.getByRole('button', { name: ASK_ABOUT_DAY_LABEL });
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });
});
