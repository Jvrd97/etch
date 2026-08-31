// [review:need-review] PHASE-03/152
// summary: component tests for the rules screen — the version in force is on the page in full, the history names both versions with their dates, the warning that the past is not recomputed sits by the publish button, editing the current version is explained as impossible rather than merely absent, and a start date that is not in the future never reaches the API

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { DayRuleSet, DayRuleSetHistory, DayRuleSetPublish } from '@/lib/api';

function rule(overrides: Partial<DayRuleSet> = {}): DayRuleSet {
  return {
    id: 2,
    valid_from: '2026-08-17',
    valid_to: null,
    timezone: 'Europe/Berlin',
    day_start_hour: 4,
    work_cap_min: 480,
    work_hard_cap_min: 540,
    work_stop_at: '16:00:00',
    max_work_tasks: 4,
    tasks_required_ratio: '1.00',
    overtime_disqualifies: true,
    overtime_lost_min: 600,
    max_study_items: 3,
    wake_at: '06:00:00',
    work_start: '09:00:00',
    review_at: '15:40:00',
    bedtime_max: '22:30:00',
    free_evening_start: '19:00:00',
    free_evening_end: '22:30:00',
    relationship_anchor_required: true,
    relationship_evening_start: '19:00:00',
    relationship_evening_end: '22:00:00',
    days_off: [6, 7],
    hard_edge_kinds: ['wake', 'sport', 'work_start', 'review', 'bedtime'],
    anchors: ['подъём', 'спорт', 'старт работы', 'ревью', 'отбой'],
    verdict_rule: {},
    workdays: [1, 2, 3, 4, 5],
    nocode_days: [2, 4],
    required_anchors: ['подъём', 'спорт', 'старт работы', 'ревью', 'отбой'],
    role_clause_enabled: true,
    role_clause_roles: 'cto,architect',
    note_md: 'действующий канон по config.md',
    ...overrides,
  };
}

const LEGACY = rule({
  id: 1,
  valid_from: '2020-01-01',
  valid_to: '2026-08-17',
  work_cap_min: 600,
  work_hard_cap_min: 600,
  tasks_required_ratio: '0.80',
  role_clause_enabled: true,
  role_clause_roles: 'cto,architect',
  note_md: 'legacy: канон до 2026-08-17',
});

const HISTORY: DayRuleSetHistory = {
  today: '2026-08-30',
  earliest_valid_from: '2026-08-31',
  current_id: 2,
  rules: [LEGACY, rule()],
};

let published: DayRuleSetPublish[] = [];
let state: {
  history: DayRuleSetHistory | null;
  loading: boolean;
  error: string | null;
  publishing: boolean;
  publishError: string | null;
  publishedFrom: string | null;
  publish: (payload: DayRuleSetPublish) => Promise<boolean>;
};

mock.module('@/hooks/useDayRules', () => ({
  useDayRules: () => state,
  LOAD_RULES_ERROR: 'Не удалось загрузить правила дня',
  PUBLISH_RULES_ERROR: 'Не удалось выпустить новую версию',
}));

const {
  default: DayRulesScreen,
  CURRENT_TITLE,
  HISTORY_TITLE,
  NO_EDIT_NOTICE,
  PAST_UNCHANGED_WARNING,
  PUBLISH_LABEL,
} = await import('./DayRulesScreen');

beforeEach(() => {
  published = [];
  state = {
    history: HISTORY,
    loading: false,
    error: null,
    publishing: false,
    publishError: null,
    publishedFrom: null,
    publish: (payload) => {
      published.push(payload);
      return Promise.resolve(true);
    },
  };
});

afterEach(() => {
  cleanup();
});

describe('DayRulesScreen', () => {
  it('shows the version in force in full — edges, ceilings, anchors', () => {
    render(<DayRulesScreen />);

    expect(screen.getByText(CURRENT_TITLE)).toBeDefined();
    expect(screen.getAllByText('8 ч в день').length).toBeGreaterThan(0);
    expect(screen.getAllByText('9 ч').length).toBeGreaterThan(0);
    expect(screen.getAllByText('16:00').length).toBeGreaterThan(0);
    expect(screen.getByText(/подъём, спорт, старт работы, ревью, отбой/)).toBeDefined();
    expect(screen.getByText(/Europe\/Berlin, с 04:00/)).toBeDefined();
  });

  it('names the free evening, though the rule row has no column for it', () => {
    render(<DayRulesScreen />);
    expect(screen.getByText(/Свободный вечер/)).toBeDefined();
  });

  it('lists every version with its dates', () => {
    render(<DayRulesScreen />);

    expect(screen.getByText(HISTORY_TITLE)).toBeDefined();
    expect(screen.getByText('2020-01-01 — 2026-08-17')).toBeDefined();
    expect(screen.getAllByText('с 2026-08-17, конца нет').length).toBeGreaterThan(0);
    // The legacy ceiling is on the page too: the history is what makes «why was
    // the 14th judged differently» answerable at all.
    expect(screen.getByText(/работа 10 ч/)).toBeDefined();
  });

  it('marks which version has already judged days and which is in force', () => {
    render(<DayRulesScreen />);
    expect(screen.getByText(/дни уже прожиты/)).toBeDefined();
    expect(screen.getByText(/действует сейчас/)).toBeDefined();
  });

  it('explains that the current version cannot be edited instead of just omitting the button', () => {
    render(<DayRulesScreen />);
    expect(screen.getByText(NO_EDIT_NOTICE)).toBeDefined();
    expect(screen.queryByText('Изменить')).toBeNull();
    expect(screen.queryByText('Сохранить')).toBeNull();
  });

  it('warns next to the publish button that the past is not recomputed', () => {
    render(<DayRulesScreen />);

    const warning = screen.getByText(PAST_UNCHANGED_WARNING);
    const button = screen.getByText(PUBLISH_LABEL);
    expect(warning).toBeDefined();
    // Не просто «где-то на странице»: предупреждение и кнопка — соседи.
    expect(warning.parentElement).toBe(button.parentElement);
  });

  it('prefills the form with the version in force', () => {
    render(<DayRulesScreen />);

    expect(screen.getByLabelText('Потолок работы, мин')).toHaveProperty('value', '480');
    expect(screen.getByLabelText('Действует с')).toHaveProperty('value', '2026-08-31');
    expect(screen.getByLabelText('Рабочие дни (ISO)')).toHaveProperty('value', '1, 2, 3, 4, 5');
  });

  it('publishes the edited version', () => {
    render(<DayRulesScreen />);

    fireEvent.change(screen.getByLabelText('Потолок работы, мин'), {
      target: { value: '420' },
    });
    fireEvent.change(screen.getByLabelText('Потолок-исключение, мин'), {
      target: { value: '420' },
    });
    fireEvent.click(screen.getByText(PUBLISH_LABEL));

    expect(published).toHaveLength(1);
    expect(published[0].work_cap_min).toBe(420);
    expect(published[0].valid_from).toBe('2026-08-31');
  });

  it('refuses a start date that is not in the future without asking the server', () => {
    render(<DayRulesScreen />);

    fireEvent.change(screen.getByLabelText('Действует с'), {
      target: { value: '2026-08-30' },
    });
    fireEvent.click(screen.getByText(PUBLISH_LABEL));

    expect(published).toEqual([]);
    expect(screen.getByRole('alert').textContent).toContain('2026-08-31');
  });

  it('shows the server refusal as the server wrote it', () => {
    state = { ...state, publishError: 'Период с 2026-09-01 перекрывает уже записанный' };
    render(<DayRulesScreen />);
    expect(screen.getByRole('alert').textContent).toContain('перекрывает');
  });

  it('confirms a published version by the date it starts on', () => {
    state = { ...state, publishedFrom: '2026-09-01' };
    render(<DayRulesScreen />);
    expect(screen.getByText(/Новая версия действует с 2026-09-01/)).toBeDefined();
  });
});
