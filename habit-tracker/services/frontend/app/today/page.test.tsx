// [review:need-review] PHASE-03/121
// summary: tests for the desktop Today screen — the quick-mark section drawn from the directory, absent entirely when the directory is empty, and the legacy quick-input card that steps aside for a category the directory covers

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, Entry, QuickMark } from '@/lib/api';

const TIMESTAMP = '2026-07-30T00:00:00Z';

/** One number category, so Today has a quick-input row and is not the empty state. */
const NUTRITION: Category = {
  id: 5,
  name: 'Питание',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  show_in_today: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [
    {
      id: 9,
      category_id: 5,
      name: 'Калории',
      field_type: 'number',
      is_required: false,
      order: 0,
      created_at: TIMESTAMP,
      updated_at: TIMESTAMP,
    },
  ],
};

/** One button of the directory, over the same category the screen shows. */
const WATER_MARK: QuickMark = {
  id: 3,
  label: '+250 мл',
  category_id: NUTRITION.id,
  field_id: 9,
  kind: 'increment',
  step: 250,
  unit_label: 'мл',
  icon: null,
  color: null,
  hotkey: null,
  order: 0,
  show_in_agent: true,
  is_active: true,
  entry_date: '2026-07-30',
  today_total: null,
  done: false,
  planned: false,
  plan_item_id: null,
};

let getCategories: ReturnType<typeof mock>;
let getEntries: ReturnType<typeof mock>;
let listQuickMarks: ReturnType<typeof mock>;
let tapQuickMark: ReturnType<typeof mock>;

// Declares the whole @/lib/api surface: bun fixes a module's export names the
// first time anything links against it and shares that registry across the run.
mock.module('@/lib/api', () => ({
  // Правила дня (#152). Есть в каждом моке api по той же причине, что и
  // остальная поверхность: bun фиксирует имена экспортов модуля при первой
  // линковке, и мок, забывший экспорт, удаляет его для всех, кто линкуется следом.
  dayRulesAPI: {
    getHistory: () => Promise.resolve(null),
    getCurrent: () => Promise.resolve(null),
    publish: () => Promise.resolve(null),
  },
  // Тренировка (#92). Есть в каждом моке api по причине, названной выше.
  trainingAPI: {
    getState: () => Promise.resolve(null),
    setProgression: () => Promise.resolve(null),
    complaints: () => Promise.resolve([]),
    openComplaint: () => Promise.resolve(null),
    closeComplaint: () => Promise.resolve(null),
    records: () => Promise.resolve([]),
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
  // Чат (#111). Есть в каждом моке api по причине, названной выше.
  chatAPI: {
    list: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
    reset: () => Promise.resolve({ reset: 0 }),
    context: () => Promise.resolve(null),
    remove: () => Promise.resolve({}),
    getPlan: () => Promise.resolve(null),
    applyPlan: () => Promise.resolve(null),
    dismissPlan: () => Promise.resolve(undefined),
    streamMessage: () => Promise.resolve(undefined),
  },
  quickMarksAPI: {
    list: () => listQuickMarks(),
    tap: (id: number) => tapQuickMark(id),
    undo: () => Promise.resolve(null),
    sources: () => Promise.resolve([]),
  },
  dayAPI: {
    getToday: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
  },
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
    getAll: () => getCategories(),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    addField: () => Promise.resolve(null),
    applyBatch: () => Promise.resolve({ categories: [], fields: [] }),
  },
  entriesAPI: {
    getAll: (params?: unknown) => getEntries(params),
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
  usePathname: () => '/today',
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

const { default: TodayPage } = await import('./page');

/** Render Today and let its catalogue, entries and directory requests settle. */
async function renderToday() {
  render(<TodayPage />);
  await waitFor(() => expect(screen.getByText('Today')).toBeDefined());
}

beforeEach(() => {
  getCategories = mock(() => Promise.resolve([NUTRITION]));
  getEntries = mock(() => Promise.resolve([] as Entry[]));
  listQuickMarks = mock(() => Promise.resolve([] as QuickMark[]));
  tapQuickMark = mock(() =>
    Promise.resolve({
      event_id: 1,
      quick_mark_id: WATER_MARK.id,
      entry_id: 5,
      entry_date: WATER_MARK.entry_date,
      occurred_at: TIMESTAMP,
      today_total: 250,
      done: true,
      planned: false,
      plan_item_id: null,
    })
  );
});

afterEach(() => {
  cleanup();
});

describe('the quick marks of /today', () => {
  it('opens without a quick-mark section when the directory is empty', async () => {
    await renderToday();

    expect(screen.queryByText('Быстрые отметки')).toBeNull();
    expect(screen.queryByRole('button', { name: WATER_MARK.label })).toBeNull();
  });

  it('draws the buttons the directory returned', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    expect(screen.getByText('Быстрые отметки')).toBeDefined();
    expect(screen.getByRole('button', { name: WATER_MARK.label })).toBeDefined();
  });

  it('sends the button id on a tap and repaints from the answer', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: WATER_MARK.label }));
    });

    expect(tapQuickMark).toHaveBeenCalledTimes(1);
    expect(tapQuickMark.mock.calls[0][0]).toBe(WATER_MARK.id);
    expect(screen.getByText('250 мл')).toBeDefined();
  });

  it('drops the legacy quick-input card of a category the directory covers', async () => {
    listQuickMarks = mock(() => Promise.resolve([WATER_MARK]));
    await renderToday();

    expect(screen.queryByLabelText('Питание: add Калории')).toBeNull();
  });

  it('keeps the card of a category the directory does not cover', async () => {
    await renderToday();

    expect(screen.getByLabelText('Питание: add Калории')).toBeDefined();
  });
});
