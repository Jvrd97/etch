// [review:need-review] PHASE-01/53-apply-plan-batch-endpoint
// summary: onboarding preview tests — default checkbox state (create on, add_field/conflict off), and that only checked ops (with edited names) reach applyBatch before redirect

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { OnboardingPlan, PlanOperation } from '@/lib/api';

const PLAN: OnboardingPlan = {
  operations: [
    {
      op: 'create_category',
      name: 'Sleep',
      description: null,
      icon: null,
      color: null,
      display_mode: 'form',
      streak_mode: 'build',
      group: null,
      fields: [
        { name: 'Hours', field_type: 'number', is_required: false, options: null, order: 0 },
      ],
      name_conflict: false,
    },
    {
      op: 'create_category',
      name: 'Water',
      description: null,
      icon: null,
      color: null,
      display_mode: 'form',
      streak_mode: 'build',
      group: null,
      fields: [],
      name_conflict: true,
    },
    {
      op: 'add_field',
      category_id: 5,
      field: { name: 'Pulse', field_type: 'number', is_required: false, options: null, order: 0 },
    },
  ],
};

let draft: ReturnType<typeof mock>;
let applyBatch: ReturnType<typeof mock>;
let pushRoute: ReturnType<typeof mock>;

// Declares the whole @/lib/api surface: bun fixes a module's export names the
// first time anything links against it and shares that registry across the run,
// so a partial mock would delete members other suites reach for.
mock.module('@/lib/api', () => ({
  // The chat client (#118). Present in every api mock for the same reason the
  // rest of the surface is: bun fixes a module's export names on first link, so
  // a mock that omits it deletes it for whoever runs next.
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
  // The day screen's client (#86). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  dayAPI: {
    getToday: () => Promise.resolve(null),
    get: () => Promise.resolve(null),
  },
  dailySummaryAPI: {
    draft: () => Promise.resolve({ metrics: [], unresolved: [] }),
    apply: () => Promise.resolve({ entry_ids: [] }),
  },
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
    applyBatch: (operations: PlanOperation[]) => applyBatch(operations),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  onboardingAPI: { draft: (text: string) => draft(text) },
  journalAPI: {
    getAll: () => Promise.resolve({ total: 0, items: [] }),
  },
}));

mock.module('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  usePathname: () => '/onboarding',
  useRouter: () => ({ push: (href: string) => pushRoute(href), replace: () => {} }),
}));

const { default: OnboardingPage } = await import('./page');

/** Render, generate a plan, and wait for the preview to settle. */
async function renderWithPlan() {
  render(<OnboardingPage />);
  fireEvent.change(screen.getByRole('textbox'), {
    target: { value: 'track my sleep and add pulse to sport' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Сгенерировать план/ }));
  await waitFor(() =>
    expect(screen.getByLabelText('Создать категорию Sleep')).toBeDefined()
  );
}

beforeEach(() => {
  draft = mock(() => Promise.resolve(PLAN));
  applyBatch = mock(() => Promise.resolve({ categories: [], fields: [] }));
  pushRoute = mock(() => {});
});

afterEach(() => {
  cleanup();
});

describe('/onboarding plan preview', () => {
  it('opts new categories in, but leaves add_field and name conflicts off', async () => {
    await renderWithPlan();

    expect(
      (screen.getByLabelText('Создать категорию Sleep') as HTMLInputElement).checked
    ).toBe(true);
    expect(
      (screen.getByLabelText('Создать категорию Water') as HTMLInputElement).checked
    ).toBe(false);
    expect(
      (screen.getByLabelText('Добавить поле Pulse') as HTMLInputElement).checked
    ).toBe(false);
  });

  it('sends only the checked ops, with edited names, then redirects', async () => {
    await renderWithPlan();

    // Rename the enabled category and turn the add_field op on.
    fireEvent.change(screen.getByLabelText('Имя категории Sleep'), {
      target: { value: 'Deep sleep' },
    });
    fireEvent.click(screen.getByLabelText('Добавить поле Pulse'));

    fireEvent.click(screen.getByRole('button', { name: /Создать выбранное/ }));

    await waitFor(() => expect(applyBatch).toHaveBeenCalledTimes(1));
    const ops = applyBatch.mock.calls[0][0] as PlanOperation[];
    // Water stays unchecked, so only Sleep (renamed) and the add_field ship.
    expect(ops).toHaveLength(2);
    expect(ops[0]).toMatchObject({ op: 'create_category', name: 'Deep sleep' });
    expect(ops[1]).toMatchObject({ op: 'add_field', category_id: 5 });

    await waitFor(() => expect(pushRoute).toHaveBeenCalledWith('/categories'));
  });

  it('does not ship unchecked ops when nothing extra is enabled', async () => {
    await renderWithPlan();

    fireEvent.click(screen.getByRole('button', { name: /Создать выбранное/ }));

    await waitFor(() => expect(applyBatch).toHaveBeenCalledTimes(1));
    const ops = applyBatch.mock.calls[0][0] as PlanOperation[];
    expect(ops).toHaveLength(1);
    expect(ops[0]).toMatchObject({ op: 'create_category', name: 'Sleep' });
  });
});
