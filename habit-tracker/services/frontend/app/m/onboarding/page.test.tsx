// [review:need-review] PHASE-01/62-mobile-onboarding-twin
// summary: integration tests for /m/onboarding — the full phone path text -> plan -> unchecked ops -> apply -> /m/categories, the narrow-screen layout rule, and the LLM error staying retryable

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { CreateCategoryOp, OnboardingPlan, PlanOperation } from '@/lib/api';

function createOp(overrides: Partial<CreateCategoryOp> = {}): CreateCategoryOp {
  return {
    op: 'create_category',
    name: 'Sleep',
    display_mode: 'form',
    streak_mode: 'build',
    fields: [{ name: 'Hours', field_type: 'number', is_required: false, order: 0 }],
    name_conflict: false,
    ...overrides,
  };
}

const ADD_FIELD_OP: PlanOperation = {
  op: 'add_field',
  category_id: 3,
  field: { name: 'Pulse', field_type: 'number', is_required: false, order: 0 },
};

let draft: ReturnType<typeof mock>;
let applyBatch: ReturnType<typeof mock>;
let push: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export names the
// first time anything links against it and shares that registry across the run,
// so a partial mock here would delete the other APIs for whichever file loads
// later.
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
  onboardingAPI: { draft: (text: string) => draft(text) },
  categoriesAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    getStreak: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    applyBatch: (operations: PlanOperation[]) => applyBatch(operations),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  insightsAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
  journalAPI: { getAll: () => Promise.resolve({ items: [] }) },
}));

mock.module('next/navigation', () => ({
  useRouter: () => ({ push, replace: () => {}, back: () => {} }),
  usePathname: () => '/m/onboarding',
  useSearchParams: () => new URLSearchParams(),
}));

const { default: MobileOnboardingPage } = await import('./page');

/** Render the screen, type a transcript and settle on the plan `draft` returns. */
async function renderWithPlan(plan: OnboardingPlan) {
  draft = mock(() => Promise.resolve(plan));
  render(<MobileOnboardingPage />);
  fireEvent.change(screen.getByLabelText('Что отслеживать'), {
    target: { value: 'трекать сон' },
  });
  fireEvent.click(screen.getByRole('button', { name: /Сгенерировать план/ }));
  await waitFor(() => expect(screen.getByRole('button', { name: /Создать выбранное/ })).toBeDefined());
}

beforeEach(() => {
  draft = mock(() => Promise.resolve({ operations: [createOp()] }));
  applyBatch = mock(() => Promise.resolve({ categories: [], fields: [] }));
  push = mock(() => {});
});

afterEach(() => {
  cleanup();
});

describe('/m/onboarding', () => {
  it('will not ask for a plan before anything is typed', () => {
    render(<MobileOnboardingPage />);

    const button = screen.getByRole('button', { name: /Сгенерировать план/ });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it('goes from text to created categories and lands on the mobile list', async () => {
    await renderWithPlan({ operations: [createOp()] });

    fireEvent.click(screen.getByRole('button', { name: /Создать выбранное/ }));

    await waitFor(() => expect(applyBatch).toHaveBeenCalled());
    expect(applyBatch.mock.calls[0][0]).toEqual([createOp()]);
    // The mobile twin, not the desktop page: leaving the shell mid-flow is the
    // one thing this screen exists to avoid.
    await waitFor(() => expect(push).toHaveBeenCalledWith('/m/categories'));
  });

  it('sends only the operations left checked, with the edited name', async () => {
    await renderWithPlan({ operations: [createOp(), createOp({ name: 'Sport' })] });

    fireEvent.click(screen.getByLabelText('Создать категорию Sport'));
    fireEvent.change(screen.getByLabelText('Имя категории Sleep'), {
      target: { value: 'Отбой' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Создать выбранное/ }));

    await waitFor(() => expect(applyBatch).toHaveBeenCalled());
    const sent = applyBatch.mock.calls[0][0] as PlanOperation[];
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ name: 'Отбой' });
  });

  it('starts a name clash and an add_field unchecked, so neither can be applied blind', async () => {
    await renderWithPlan({
      operations: [createOp({ name: 'Sport', name_conflict: true }), ADD_FIELD_OP],
    });

    expect((screen.getByLabelText('Создать категорию Sport') as HTMLInputElement).checked).toBe(
      false
    );
    expect((screen.getByLabelText('Добавить поле Pulse') as HTMLInputElement).checked).toBe(
      false
    );
    const apply = screen.getByRole('button', { name: /Создать выбранное \(0\)/ });
    expect((apply as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the clash so the name can be fixed before applying', async () => {
    await renderWithPlan({ operations: [createOp({ name: 'Sport', name_conflict: true })] });

    expect(screen.getByText('имя уже занято')).toBeDefined();
  });

  it('keeps the screen usable and offers Retry when the LLM is down', async () => {
    draft = mock(() => Promise.reject(new Error('LLM backend unavailable')));
    render(<MobileOnboardingPage />);

    fireEvent.change(screen.getByLabelText('Что отслеживать'), {
      target: { value: 'трекать сон' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Сгенерировать план/ }));

    await waitFor(() => expect(screen.getByText('LLM backend unavailable')).toBeDefined());
    draft = mock(() => Promise.resolve({ operations: [createOp()] }));
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Создать выбранное/ })).toBeDefined()
    );
  });

  it('keeps the plan on screen when the batch is rejected', async () => {
    applyBatch = mock(() => Promise.reject(new Error('name already taken')));
    await renderWithPlan({ operations: [createOp()] });

    fireEvent.click(screen.getByRole('button', { name: /Создать выбранное/ }));

    await waitFor(() => expect(screen.getByText('name already taken')).toBeDefined());
    expect(screen.getByLabelText('Имя категории Sleep')).toBeDefined();
    expect(push).not.toHaveBeenCalled();
  });

  it('says so plainly when the model proposed nothing', async () => {
    draft = mock(() => Promise.resolve({ operations: [] }));
    render(<MobileOnboardingPage />);

    fireEvent.change(screen.getByLabelText('Что отслеживать'), {
      target: { value: 'ничего' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Сгенерировать план/ }));

    await waitFor(() => expect(screen.getByText(/не предложила изменений/)).toBeDefined());
  });

  it('never puts two preview controls side by side on a narrow screen', async () => {
    await renderWithPlan({ operations: [createOp(), ADD_FIELD_OP] });

    // The desktop preview packs the checkbox, the name input and the conflict
    // badge into one row; at 375pt that is what pushes the page sideways.
    const columns = document.body.querySelectorAll(
      '[class*="grid-cols-2"], [class*="grid-cols-3"]'
    );
    expect(columns).toHaveLength(0);
  });
});
