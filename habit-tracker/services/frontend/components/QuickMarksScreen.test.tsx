// [review:need-review] PHASE-03/125
// summary: component tests for the directory screen — a button is entered from the form rather than by SQL, a taken key names its holder and leaves the filled-in form on screen, the field picker offers only the fields the kind can write to, the step is refused before the request, deletion says what it does not touch, and switched-off buttons stay on the screen that exists to switch them back on

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { Category, HotkeyTaken, QuickMark, QuickMarkDraft } from '@/lib/api';

function mark(overrides: Partial<QuickMark> = {}): QuickMark {
  return {
    id: 1,
    label: '+250 мл',
    category_id: 10,
    field_id: 100,
    kind: 'increment',
    step: 250,
    unit_label: 'мл',
    icon: null,
    color: null,
    hotkey: 'w',
    order: 0,
    show_in_agent: true,
    is_active: true,
    entry_date: '2026-08-31',
    today_total: null,
    done: false,
    planned: false,
    plan_item_id: null,
    ...overrides,
  };
}

const WATER: Category = {
  id: 10,
  name: 'Вода',
  display_mode: 'form',
  streak_mode: 'build',
  is_active: true,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  fields: [
    {
      id: 100,
      category_id: 10,
      name: 'Объём',
      field_type: 'number',
      is_required: false,
      order: 0,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:00:00Z',
    },
    {
      id: 101,
      category_id: 10,
      name: 'Заметка',
      field_type: 'text',
      is_required: false,
      order: 1,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:00:00Z',
    },
  ],
};

const TAKEN: HotkeyTaken = {
  error: 'hotkey_taken',
  message: 'клавиша \'w\' уже стоит у кнопки «Вода» (id 1)',
  hotkey: 'w',
  quick_mark_id: 1,
  label: 'Вода',
};

let created: QuickMarkDraft[] = [];
let updated: [number, QuickMarkDraft][] = [];
let removed: number[] = [];
let moved: [number, number][] = [];
let createResult = true;
let state: {
  marks: QuickMark[];
  categories: Category[];
  loading: boolean;
  error: string | null;
  conflict: HotkeyTaken | null;
  create: (draft: QuickMarkDraft) => Promise<boolean>;
  update: (id: number, draft: QuickMarkDraft) => Promise<boolean>;
  remove: (id: number) => Promise<boolean>;
  move: (id: number, delta: number) => Promise<boolean>;
  dismiss: () => void;
  reload: () => void;
};

mock.module('@/hooks/useQuickMarkAdmin', () => ({
  useQuickMarkAdmin: () => state,
  SAVE_FAILED: 'Сохранить не удалось.',
}));

const {
  default: QuickMarksScreen,
  DELETE_CONFIRM_HINT,
  DELETE_CONFIRM_LABEL,
  DELETE_LABEL,
  EDIT_LABEL,
  NEW_MARK_LABEL,
  moveMarkDownLabel,
} = await import('./QuickMarksScreen');
const { SAVE_LABEL, SHOW_IN_AGENT_LABEL } = await import('./QuickMarkEditor');
const { STEP_REQUIRED_ERROR } = await import('@/lib/quick-mark-form');

beforeEach(() => {
  created = [];
  updated = [];
  removed = [];
  moved = [];
  createResult = true;
  state = {
    marks: [mark()],
    categories: [WATER],
    loading: false,
    error: null,
    conflict: null,
    create: (draft) => {
      created.push(draft);
      return Promise.resolve(createResult);
    },
    update: (id, draft) => {
      updated.push([id, draft]);
      return Promise.resolve(true);
    },
    remove: (id) => {
      removed.push(id);
      return Promise.resolve(true);
    },
    move: (id, delta) => {
      moved.push([id, delta]);
      return Promise.resolve(true);
    },
    dismiss: () => {},
    reload: () => {},
  };
});

afterEach(() => {
  cleanup();
});

/** Fill the form with a valid new button, without pressing Save. */
function fillNewButton(): void {
  fireEvent.click(screen.getByRole('button', { name: NEW_MARK_LABEL }));
  fireEvent.change(screen.getByLabelText('Подпись'), { target: { value: '+300 мл' } });
  fireEvent.change(screen.getByLabelText('Категория'), { target: { value: '10' } });
  fireEvent.change(screen.getByLabelText('Поле'), { target: { value: '100' } });
  fireEvent.change(screen.getByLabelText('Шаг'), { target: { value: '300' } });
  fireEvent.change(screen.getByLabelText('Клавиша'), { target: { value: 'w' } });
}

describe('QuickMarksScreen', () => {
  it('enters a button from the form — no SQL anywhere in the path', () => {
    render(<QuickMarksScreen />);
    fillNewButton();
    fireEvent.click(screen.getByRole('button', { name: SAVE_LABEL }));

    expect(created).toHaveLength(1);
    expect(created[0]).toMatchObject({
      label: '+300 мл',
      category_id: 10,
      field_id: 100,
      kind: 'increment',
      step: 300,
      hotkey: 'w',
    });
  });

  it('names the button holding the key and keeps everything typed in', () => {
    createResult = false;
    render(<QuickMarksScreen />);
    fillNewButton();
    fireEvent.click(screen.getByRole('button', { name: SAVE_LABEL }));

    // The screen re-renders with the conflict the hook now holds; the form must
    // still be the one the person filled in.
    state = { ...state, conflict: TAKEN, error: TAKEN.message };
    fireEvent.change(screen.getByLabelText('Единица'), { target: { value: 'мл' } });

    expect((screen.getByLabelText('Подпись') as HTMLInputElement).value).toBe('+300 мл');
    expect((screen.getByLabelText('Шаг') as HTMLInputElement).value).toBe('300');
    expect((screen.getByLabelText('Клавиша') as HTMLInputElement).value).toBe('w');
    expect(screen.getByRole('alert').textContent).toContain('Вода');
  });

  it('offers only the fields the chosen kind can write to', () => {
    render(<QuickMarksScreen />);
    fireEvent.click(screen.getByRole('button', { name: NEW_MARK_LABEL }));
    fireEvent.change(screen.getByLabelText('Категория'), { target: { value: '10' } });

    const options = Array.from(
      (screen.getByLabelText('Поле') as HTMLSelectElement).options
    ).map((option) => option.textContent);
    expect(options).toContain('Объём');
    expect(options).not.toContain('Заметка');
  });

  it('refuses an increment without a step before the request leaves', () => {
    render(<QuickMarksScreen />);
    fireEvent.click(screen.getByRole('button', { name: NEW_MARK_LABEL }));
    fireEvent.change(screen.getByLabelText('Подпись'), { target: { value: '+300 мл' } });
    fireEvent.change(screen.getByLabelText('Категория'), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText('Поле'), { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: SAVE_LABEL }));

    expect(created).toHaveLength(0);
    expect(screen.getByText(STEP_REQUIRED_ERROR)).toBeDefined();
  });

  it('takes the agent switch off with one action and writes it', () => {
    render(<QuickMarksScreen />);
    fireEvent.click(screen.getByRole('button', { name: EDIT_LABEL }));
    fireEvent.click(screen.getByLabelText(SHOW_IN_AGENT_LABEL));
    fireEvent.click(screen.getByRole('button', { name: SAVE_LABEL }));

    expect(updated).toHaveLength(1);
    expect(updated[0][0]).toBe(1);
    expect(updated[0][1].show_in_agent).toBe(false);
  });

  it('says what deletion does not touch, and deletes only after confirmation', () => {
    render(<QuickMarksScreen />);
    fireEvent.click(screen.getByRole('button', { name: DELETE_LABEL }));

    expect(screen.getByText(DELETE_CONFIRM_HINT)).toBeDefined();
    expect(removed).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: DELETE_CONFIRM_LABEL }));
    expect(removed).toEqual([1]);
  });

  it('moves a button one place at a time', () => {
    state = { ...state, marks: [mark(), mark({ id: 2, label: 'D3', hotkey: 'd' })] };
    render(<QuickMarksScreen />);
    fireEvent.click(screen.getByRole('button', { name: moveMarkDownLabel(1) }));

    expect(moved).toEqual([[1, 1]]);
  });

  it('keeps a switched-off button on the screen that switches it back on', () => {
    state = { ...state, marks: [mark({ is_active: false })] };
    render(<QuickMarksScreen />);

    expect(screen.getByText('+250 мл')).toBeDefined();
    expect(screen.getByText(/выключена/)).toBeDefined();
  });
});
