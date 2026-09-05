// [review:need-review] PHASE-01/73-category-field-reorder, 175
// summary: integration tests for the mobile category editor, including explicit table-field selection and clearing

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Category, Field } from '@/lib/api';

const TIMESTAMP = '2026-07-24T00:00:00Z';

function field(id: number, name: string, order: number): Field {
  return {
    id,
    category_id: 1,
    name,
    field_type: 'text',
    is_required: false,
    order,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
  };
}

const HOURS_FIELD = field(7, 'Hours', 0);
const QUALITY_FIELD = field(8, 'Quality', 1);

const CATEGORY: Category = {
  id: 1,
  name: 'Sleep',
  color: '#123456',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: TIMESTAMP,
  updated_at: TIMESTAMP,
  fields: [HOURS_FIELD, QUALITY_FIELD],
};

let getAllCategories: ReturnType<typeof mock>;
let createCategory: ReturnType<typeof mock>;
let updateCategory: ReturnType<typeof mock>;
let deleteCategory: ReturnType<typeof mock>;

// Declares the whole surface on purpose: bun fixes a module's export *names* the
// first time anything links against it and shares that registry across the run,
// so a partial mock here would delete `tableAPI` for whichever file loads later.
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
  // The goal board's client (#93). Present in every api mock for the same
  // reason the rest of the surface is: bun fixes a module's export names on
  // first link, so a mock that omits it deletes it for whoever runs next.
  goalsAPI: {
    get: () => Promise.resolve(null),
    patchMilestone: () => Promise.resolve(null),
  },
  // The quick-mark directory and its one write path (#121). Present in every
  // api mock for the reason named above: bun fixes a module's export names on
  // first link, so a mock that omits an export deletes it for whoever links next.
  quickMarksAPI: {
    list: () => Promise.resolve([]),
    tap: () => Promise.resolve(null),
    undo: () => Promise.resolve(null),
    sources: () => Promise.resolve([]),
  },
  // The Today screen carries the challenge block (#127). Present in every api
  // mock for the same reason the rest of the surface is: bun fixes a module's
  // export names on first link, so a mock that omits it deletes it for whoever
  // runs next.
  challengesAPI: {
    list: () => Promise.resolve([]),
    get: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
    patch: () => Promise.resolve(null),
    recompute: () => Promise.resolve(null),
  },
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
  onboardingAPI: { draft: () => Promise.resolve({ operations: [] }) },
  insightsAPI: {
    getAll: () => Promise.resolve([]),
    getById: () => Promise.resolve(null),
    create: () => Promise.resolve(null),
  },
  categoriesAPI: {
    getAll: (activeOnly?: boolean) => getAllCategories(activeOnly),
    getById: () => Promise.resolve(CATEGORY),
    getStreak: () => Promise.resolve(null),
    create: (data: unknown) => createCategory(data),
    update: (id: number, data: unknown) => updateCategory(id, data),
    delete: (id: number) => deleteCategory(id),
  },
  entriesAPI: {
    getAll: () => Promise.resolve([]),
    create: () => Promise.resolve(null),
    update: () => Promise.resolve(null),
    delete: () => Promise.resolve(undefined),
    upsertChecklist: () => Promise.resolve({}),
  },
  tableAPI: { get: () => Promise.resolve({ days: [] }) },
}));

const { default: MobileCategoriesPage } = await import('./page');
const { NEW_CATEGORY_SHEET_TITLE, TAP_TARGET_PX } = await import('@/lib/ui-constants');
const { fieldMovedMessage } = await import('@/hooks/useCategories');

/** Narrowest phone this shell is expected to survive. */
const NARROW_SCREEN_PX = 320;

/** Render the screen and wait for the first load to settle. */
async function renderPage() {
  render(<MobileCategoriesPage />);
  await waitFor(() => expect(screen.getByText('Sleep')).toBeDefined());
}

/** The open editor sheet. */
function sheet(): HTMLElement {
  return screen.getByRole('dialog');
}

beforeEach(() => {
  getAllCategories = mock(() => Promise.resolve([CATEGORY]));
  createCategory = mock(() => Promise.resolve(CATEGORY));
  updateCategory = mock(() => Promise.resolve(CATEGORY));
  deleteCategory = mock(() => Promise.resolve(undefined));
});

afterEach(() => {
  cleanup();
});

describe('/m/categories', () => {
  it('lists the categories with a link into their detail screen', async () => {
    await renderPage();

    const link = screen.getByRole('link', { name: /Sleep/ });
    expect(link.getAttribute('href')).toBe('/m/categories/1');
  });

  it('creates a category from the sheet', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'New category' }));
    expect(screen.getByRole('dialog', { name: NEW_CATEGORY_SHEET_TITLE })).toBeDefined();

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Reading' } });
    fireEvent.change(screen.getByLabelText('Field 1 name'), { target: { value: 'Pages' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(createCategory).toHaveBeenCalled());
    expect(createCategory.mock.calls[0][0]).toMatchObject({
      name: 'Reading',
      fields: [{ name: 'Pages', order: 0 }],
    });
    // The sheet closes on success, back to the list.
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('adds a field and saves it', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add field' }));
    fireEvent.change(screen.getByLabelText('Field 3 name'), { target: { value: 'Dreams' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    const payload = updateCategory.mock.calls[0][1] as { fields: { name: string }[] };
    expect(payload.fields.map((f) => f.name)).toEqual(['Hours', 'Quality', 'Dreams']);
  });

  it('removes a field and saves the removal', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove field 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    const payload = updateCategory.mock.calls[0][1] as { fields: { id?: number }[] };
    expect(payload.fields).toEqual([expect.objectContaining({ id: 8, order: 0 })]);
  });

  it('moves a field up and saves the new order with the ids intact', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Move field 2 up' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    const payload = updateCategory.mock.calls[0][1] as { fields: { id?: number }[] };
    // Reordering must not look like a delete-and-recreate to the backend, or
    // every value logged against the moved field goes with it.
    expect(payload.fields).toEqual([
      expect.objectContaining({ id: 8, name: 'Quality', order: 0 }),
      expect.objectContaining({ id: 7, name: 'Hours', order: 1 }),
    ]);
  });

  it('moves a field back down again', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Move field 2 up' }));
    fireEvent.click(screen.getByRole('button', { name: 'Move field 1 down' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    const payload = updateCategory.mock.calls[0][1] as { fields: { id?: number }[] };
    expect(payload.fields.map((f) => f.id)).toEqual([7, 8]);
  });

  it('has nowhere to go at either end of the field list', async () => {
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));

    const firstUp = screen.getByRole('button', { name: 'Move field 1 up' }) as HTMLButtonElement;
    const lastDown = screen.getByRole('button', {
      name: 'Move field 2 down',
    }) as HTMLButtonElement;
    expect(firstUp.disabled).toBe(true);
    expect(lastDown.disabled).toBe(true);
    expect(
      (screen.getByRole('button', { name: 'Move field 2 up' }) as HTMLButtonElement).disabled
    ).toBe(false);
  });

  it('carries the row DOM with the field, so the inputs do not swap contents', async () => {
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));

    const secondNameInput = screen.getByLabelText('Field 2 name');
    fireEvent.click(screen.getByRole('button', { name: 'Move field 2 up' }));

    // Same node now answering to position 1: index-keyed rows would instead
    // reuse the DOM that already sat there, taking the focus and the caret of
    // whoever was typing to a different field.
    expect(screen.getByLabelText('Field 1 name')).toBe(secondNameInput);
    expect((screen.getByLabelText('Field 1 name') as HTMLInputElement).value).toBe('Quality');
  });

  it('announces where the moved field landed', async () => {
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));

    fireEvent.click(screen.getByRole('button', { name: 'Move field 2 up' }));

    // Without the live region the reorder is silent: the cards swap places and
    // a screen reader has nothing to report.
    expect(screen.getByRole('status').textContent).toBe(fieldMovedMessage(1));
  });

  it('keeps the focus on a button that still does something after a move', async () => {
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));

    fireEvent.click(screen.getByRole('button', { name: 'Move field 2 up' }));

    // The pressed button travelled with its card to position 1, where "up" is
    // disabled: leaving focus there strands the keyboard on an inert control,
    // so it moves to the button that undoes the move.
    expect(document.activeElement).toBe(
      screen.getByRole('button', { name: 'Move field 1 down' })
    );
  });

  it('lets a field card wrap rather than shrink its tap targets on a 320px screen', async () => {
    window.innerWidth = NARROW_SCREEN_PX;
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));

    const actions = ['Move field 1 up', 'Move field 1 down', 'Remove field 1'].map((name) =>
      screen.getByRole('button', { name })
    );
    for (const button of actions) {
      expect(button.style.minWidth).toBe(`${TAP_TARGET_PX}px`);
      expect(button.style.minHeight).toBe(`${TAP_TARGET_PX}px`);
    }

    // Same rule as "no form control two-in-a-row on a narrow screen", one level
    // down: three 44px targets plus the Required checkbox declare more width
    // than a 320px screen has left after the sheet's and the card's padding, so
    // the row that holds them has to be allowed to wrap. Without that the
    // browser resolves the overflow by squeezing the targets below tap size.
    const row = actions[0].parentElement?.parentElement;
    expect(row?.className).toContain('flex-wrap');
  });

  it('renames a field without losing its id, so the edit really persists', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.change(screen.getByLabelText('Field 1 name'), { target: { value: 'Slept' } });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    const payload = updateCategory.mock.calls[0][1] as { fields: { id?: number; name: string }[] };
    expect(payload.fields[0]).toMatchObject({ id: 7, name: 'Slept' });
  });

  it('reloads the list once the save went through', async () => {
    await renderPage();
    const loadsBefore = getAllCategories.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() =>
      expect(getAllCategories.mock.calls.length).toBeGreaterThan(loadsBefore)
    );
  });

  it('keeps the sheet open and shows why when the save is rejected', async () => {
    await renderPage();
    updateCategory = mock(() => Promise.reject(new Error('name already taken')));

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(screen.getByText('name already taken')).toBeDefined());
    expect(screen.queryByRole('dialog')).not.toBeNull();
  });

  it('never puts two form controls side by side in the sheet', async () => {
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));

    // The desktop modal packs Display/Streak mode and Colour/Active into
    // `grid-cols-2`, which on a phone leaves two unusable half-width controls.
    const columns = sheet().querySelectorAll('[class*="grid-cols-2"], [class*="grid-cols-3"]');
    expect(columns).toHaveLength(0);
  });

  it('discards the draft when the sheet is cancelled', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Rest' } });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(updateCategory).not.toHaveBeenCalled();
  });

  it('deletes a category once the confirmation is accepted', async () => {
    const confirmSpy = mock(() => true);
    globalThis.confirm = confirmSpy as unknown as typeof globalThis.confirm;
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Delete Sleep' }));

    await waitFor(() => expect(deleteCategory).toHaveBeenCalledWith(1));
    expect(confirmSpy).toHaveBeenCalled();
  });

  it('leaves the category alone when the confirmation is declined', async () => {
    globalThis.confirm = (() => false) as unknown as typeof globalThis.confirm;
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Delete Sleep' }));

    expect(deleteCategory).not.toHaveBeenCalled();
  });

  it('offers a way in when there is no category yet', async () => {
    getAllCategories = mock(() => Promise.resolve([]));
    render(<MobileCategoriesPage />);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Create category' })).toBeDefined()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Create category' }));
    expect(screen.getByRole('dialog', { name: NEW_CATEGORY_SHEET_TITLE })).toBeDefined();
  });

  it('pins a category to Today from the editor sheet', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.change(screen.getByLabelText('Show on Today'), {
      target: { value: 'always' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    expect(updateCategory.mock.calls[0][1]).toMatchObject({ show_in_today: true });
  });

  it('removes a category from Today without deactivating it', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.change(screen.getByLabelText('Show on Today'), {
      target: { value: 'never' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    expect(updateCategory.mock.calls[0][1]).toMatchObject({
      show_in_today: false,
      is_active: true,
    });
  });

  it('loads the selected table field and sends an explicit clear from the editor', async () => {
    const categoryWithPrimary = { ...CATEGORY, primary_field_id: QUALITY_FIELD.id };
    getAllCategories = mock(() => Promise.resolve([categoryWithPrimary]));
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));

    const selectedRadio = screen.getByLabelText(
      'Показывать в таблице: Quality'
    ) as HTMLInputElement;
    expect(selectedRadio.checked).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Сбросить выбор' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    expect(updateCategory.mock.calls[0][1]).toMatchObject({ primary_field_id: null });
  });

  it('sends the id of the field selected for the table', async () => {
    await renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit Sleep' }));
    fireEvent.click(screen.getByLabelText('Показывать в таблице: Quality'));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(updateCategory).toHaveBeenCalled());
    expect(updateCategory.mock.calls[0][1]).toMatchObject({ primary_field_id: QUALITY_FIELD.id });
  });

  it('offers the builder alongside the form when there is no category yet', async () => {
    getAllCategories = mock(() => Promise.resolve([]));
    render(<MobileCategoriesPage />);

    // Beside the one-field-at-a-time form, not instead of it: from nothing, the
    // builder is the faster way in, and it must stay inside the mobile shell.
    await waitFor(() =>
      expect(screen.getByRole('link', { name: /Describe them instead/ })).toBeDefined()
    );
    expect(
      screen.getByRole('link', { name: /Describe them instead/ }).getAttribute('href')
    ).toBe('/m/onboarding');
    expect(screen.getByRole('button', { name: 'Create category' })).toBeDefined();
  });
});
