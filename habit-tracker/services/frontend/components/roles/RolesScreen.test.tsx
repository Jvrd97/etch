// [review:need-review] PHASE-03/134
// summary: component tests for the role screen — the manual form sends «90 минут, архитектор, найм» with nothing else set up, a record typed by a person is marked as such, the target share is never printed without the word «гипотеза», and a day with no records says so instead of looking broken

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type {
  Role,
  RoleAct,
  RoleActDraft,
  RoleDay,
  RoleTimeBlockDraft,
} from '@/lib/api';

const ROLES: Role[] = [
  {
    id: 1,
    code: 'cto',
    title: 'CTO',
    description: null,
    target_share_pct: 25,
    is_work: true,
    ord: 1,
    is_active: true,
  },
  {
    id: 2,
    code: 'architect',
    title: 'Системный архитектор',
    description: null,
    target_share_pct: 25,
    is_work: true,
    ord: 2,
    is_active: true,
  },
  {
    id: 3,
    code: 'techlead',
    title: 'Тимлид',
    description: null,
    target_share_pct: 50,
    is_work: true,
    ord: 3,
    is_active: true,
  },
];

const ADR_ACT: RoleAct = {
  id: 1,
  work_day: '2026-08-30',
  role_id: 2,
  role_code: 'architect',
  act_kind: 'adr_written',
  title: 'ADR-0020',
  source: 'manual',
  external_ref: null,
  confidence: 'auto',
  occurred_at: null,
  note: null,
  is_manual: true,
};

function emptyDay(): RoleDay {
  return {
    work_day: '2026-08-30',
    total_minutes: 0,
    roles: ROLES.map((role) => ({
      role_id: role.id,
      role_code: role.code,
      title: role.title,
      minutes: 0,
      share_pct: 0,
      target_share_pct: role.target_share_pct,
      act_count: 0,
    })),
    blocks: [],
    acts: [],
  };
}

function dayWithHiring(): RoleDay {
  return {
    work_day: '2026-08-30',
    total_minutes: 90,
    roles: ROLES.map((role) => ({
      role_id: role.id,
      role_code: role.code,
      title: role.title,
      minutes: role.code === 'architect' ? 90 : 0,
      share_pct: role.code === 'architect' ? 100 : 0,
      target_share_pct: role.target_share_pct,
      act_count: role.code === 'architect' ? 1 : 0,
    })),
    blocks: [
      {
        id: 5,
        work_day: '2026-08-30',
        role_id: 2,
        role_code: 'architect',
        source: 'manual',
        started_at: null,
        ended_at: null,
        minutes: 90,
        confidence: 'auto',
        external_ref: null,
        rule_id: null,
        note: 'найм',
        is_manual: true,
      },
    ],
    acts: [ADR_ACT],
  };
}

const written: RoleTimeBlockDraft[] = [];
const acts: RoleActDraft[] = [];

let state: {
  day: RoleDay | null;
  roles: Role[];
  loading: boolean;
  saving: boolean;
  error: string | null;
  addTimeBlock: (draft: RoleTimeBlockDraft) => Promise<void>;
  addAct: (draft: RoleActDraft) => Promise<void>;
  deleteTimeBlock: (id: number) => Promise<void>;
};

mock.module('@/hooks/useRoles', () => ({
  useRoles: () => state,
}));

const { default: RolesScreen } = await import('./RolesScreen');
const { MANUAL_MARK, NO_ACTS_TEXT, NO_MINUTES_TEXT, TARGET_SHARE_HYPOTHESIS } =
  await import('@/lib/role-format');

beforeEach(() => {
  written.length = 0;
  acts.length = 0;
  state = {
    day: emptyDay(),
    roles: ROLES,
    loading: false,
    saving: false,
    error: null,
    addTimeBlock: async (draft) => {
      written.push(draft);
    },
    addAct: async (draft) => {
      acts.push(draft);
    },
    deleteTimeBlock: async () => {},
  };
});

afterEach(cleanup);

describe('RolesScreen', () => {
  it('records ninety minutes on hiring with nothing else set up', () => {
    render(<RolesScreen />);

    fireEvent.change(screen.getByLabelText('Роль', { selector: '#minutes-role' }), {
      target: { value: 'architect' },
    });
    fireEvent.change(screen.getByLabelText('Минуты'), { target: { value: '90' } });
    fireEvent.change(screen.getByLabelText('Чем занимался'), {
      target: { value: 'найм' },
    });
    fireEvent.click(screen.getByText('Записать'));

    expect(written).toEqual([
      {
        role_code: 'architect',
        minutes: 90,
        work_day: '2026-08-30',
        note: 'найм',
      },
    ]);
  });

  it('records an act with its kind and title', () => {
    render(<RolesScreen />);

    fireEvent.change(screen.getByLabelText('Роль', { selector: '#act-role' }), {
      target: { value: 'architect' },
    });
    fireEvent.change(screen.getByLabelText('Вид акта'), {
      target: { value: 'adr_written' },
    });
    fireEvent.change(screen.getByLabelText('Что это было'), {
      target: { value: 'ADR-0020' },
    });
    fireEvent.click(screen.getByText('Записать акт'));

    expect(acts).toEqual([
      {
        role_code: 'architect',
        act_kind: 'adr_written',
        title: 'ADR-0020',
        work_day: '2026-08-30',
      },
    ]);
  });

  it('refuses to send an act with no title', () => {
    render(<RolesScreen />);
    fireEvent.click(screen.getByText('Записать акт'));
    expect(acts).toEqual([]);
  });

  it('says out loud that a day carries no minutes and no acts', () => {
    render(<RolesScreen />);
    expect(screen.getByText(NO_MINUTES_TEXT)).toBeDefined();
    expect(screen.getAllByText(NO_ACTS_TEXT).length).toBeGreaterThan(0);
  });

  it('marks a record a person typed', () => {
    state = { ...state, day: dayWithHiring() };
    render(<RolesScreen />);
    expect(screen.getAllByText(new RegExp(MANUAL_MARK)).length).toBeGreaterThan(0);
  });

  it('never prints a target share without calling it a hypothesis', () => {
    state = { ...state, day: dayWithHiring() };
    const { container } = render(<RolesScreen />);
    const targets = Array.from(container.querySelectorAll('p')).filter((node) =>
      /цель \d+%/.test(node.textContent ?? '')
    );
    expect(targets.length).toBeGreaterThan(0);
    expect(
      targets.every((node) => (node.textContent ?? '').includes(TARGET_SHARE_HYPOTHESIS))
    ).toBe(true);
  });

  it('shows the act of the day and which role carried it', () => {
    state = { ...state, day: dayWithHiring() };
    render(<RolesScreen />);
    expect(screen.getByText(/написан ADR: ADR-0020/)).toBeDefined();
    expect(screen.getByText(/Системный архитектор — 1 акт/)).toBeDefined();
    expect(screen.queryByText(NO_ACTS_TEXT)).toBeNull();
  });
});
