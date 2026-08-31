// [review:need-review] PHASE-03/135
// summary: component tests of the markup on the roles screen — an automatic record is marked as such and opens up to the rule and the application behind it, the confirm button appears only on an unconfirmed automatic record and freezes it, a manual record stays untouched, and the share nothing could be attributed to is printed as a number

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { Role, RoleDay, RoleTimeBlock } from '@/lib/api';
import {
  AUTOMATIC_MARK,
  CONFIRM_LABEL,
  CONFIRMED_MARK,
  markupSource,
  unassignedLine,
} from '@/lib/role-format';

const ROLES: Role[] = [
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
  {
    id: 4,
    code: 'unassigned',
    title: 'Не отнесено',
    description: null,
    target_share_pct: null,
    is_work: false,
    ord: 4,
    is_active: true,
  },
];

function block(overrides: Partial<RoleTimeBlock> = {}): RoleTimeBlock {
  return {
    id: 7,
    work_day: '2026-08-31',
    role_id: 3,
    role_code: 'techlead',
    source: 'app_usage',
    started_at: '2026-08-31T08:00:00Z',
    ended_at: '2026-08-31T10:00:00Z',
    minutes: 120,
    confidence: 'auto',
    external_ref: '11:2026-08-31',
    rule_id: 2,
    note: null,
    is_manual: false,
    is_automatic: true,
    rule_summary: 'bundle_id = com.microsoft.VSCode',
    app_name: 'VS Code',
    ...overrides,
  };
}

function day(blocks: RoleTimeBlock[], unassignedMinutes = 60): RoleDay {
  const techleadMinutes = blocks.reduce((sum, row) => sum + row.minutes, 0);
  const total = techleadMinutes + unassignedMinutes;
  return {
    work_day: '2026-08-31',
    total_minutes: total,
    roles: [
      {
        role_id: 3,
        role_code: 'techlead',
        title: 'Тимлид',
        minutes: techleadMinutes,
        share_pct: total ? Math.round((techleadMinutes * 100) / total) : 0,
        target_share_pct: 50,
        act_count: 0,
      },
      {
        role_id: 4,
        role_code: 'unassigned',
        title: 'Не отнесено',
        minutes: unassignedMinutes,
        share_pct: total ? Math.round((unassignedMinutes * 100) / total) : 0,
        target_share_pct: null,
        act_count: 0,
      },
    ],
    blocks,
    acts: [],
  };
}

const confirmed = mock((_: number) => Promise.resolve());

function screenWith(blocks: RoleTimeBlock[], unassignedMinutes = 60) {
  mock.module('@/hooks/useRoles', () => ({
    useRoles: () => ({
      day: day(blocks, unassignedMinutes),
      roles: ROLES,
      loading: false,
      saving: false,
      error: null,
      addTimeBlock: () => Promise.resolve(),
      addAct: () => Promise.resolve(),
      deleteTimeBlock: () => Promise.resolve(),
      confirmTimeBlock: confirmed,
    }),
  }));
}

afterEach(() => {
  cleanup();
  confirmed.mockClear();
});

describe('подпись автоматической записи', () => {
  it('называет и приложение, и правило', () => {
    expect(markupSource(block())).toBe(
      `${AUTOMATIC_MARK}: VS Code · bundle_id = com.microsoft.VSCode`
    );
  });

  it('называет приложение, когда правила уже нет', () => {
    expect(markupSource(block({ rule_id: null, rule_summary: null }))).toBe(
      `${AUTOMATIC_MARK}: VS Code`
    );
  });

  it('на ручной записи молчит', () => {
    expect(
      markupSource(
        block({
          is_automatic: false,
          is_manual: true,
          source: 'manual',
          rule_summary: null,
          app_name: null,
        })
      )
    ).toBeNull();
  });
});

describe('доля «не отнесено»', () => {
  it('печатается числом', () => {
    expect(unassignedLine(day([block()]))).toBe('не отнесено: 33%');
  });

  it('молчит, когда всё отнесено', () => {
    expect(unassignedLine(day([block()], 0))).toBeNull();
  });
});

describe('экран ролей', () => {
  it('помечает запись автоматической и раскрывает правило', async () => {
    screenWith([block()]);
    const { default: RolesScreen } = await import('./RolesScreen');
    render(<RolesScreen />);
    expect(
      screen.getByText(`${AUTOMATIC_MARK}: VS Code · bundle_id = com.microsoft.VSCode`)
    ).toBeTruthy();
    expect(screen.getByText('не отнесено: 33%')).toBeTruthy();
  });

  it('кнопка «подтвердить» замораживает запись', async () => {
    screenWith([block()]);
    const { default: RolesScreen } = await import('./RolesScreen');
    render(<RolesScreen />);
    fireEvent.click(screen.getByText(CONFIRM_LABEL));
    expect(confirmed).toHaveBeenCalledWith(7);
  });

  it('у подтверждённой записи кнопки уже нет', async () => {
    screenWith([block({ confidence: 'confirmed' })]);
    const { default: RolesScreen } = await import('./RolesScreen');
    render(<RolesScreen />);
    expect(screen.queryByText(CONFIRM_LABEL)).toBeNull();
    expect(screen.getByText(new RegExp(CONFIRMED_MARK))).toBeTruthy();
  });

  it('у ручной записи кнопки «подтвердить» нет', async () => {
    screenWith([
      block({
        is_automatic: false,
        is_manual: true,
        source: 'manual',
        rule_summary: null,
        app_name: null,
      }),
    ]);
    const { default: RolesScreen } = await import('./RolesScreen');
    render(<RolesScreen />);
    expect(screen.queryByText(CONFIRM_LABEL)).toBeNull();
  });
});
