// [review:need-review] PHASE-03/134
// summary: tests for the role labels — the target share never appears without the word «гипотеза», a day with one architect act reads differently from a day with none, acts count in countable Russian, and an act kind the map has not caught up with shows its code

import { describe, expect, it } from 'bun:test';
import type { RoleAct, RoleDay, RoleDaySlice } from '@/lib/api';
import {
  ACT_KIND_OPTIONS,
  NO_ACTS_TEXT,
  TARGET_SHARE_HYPOTHESIS,
  actKindLabel,
  actLine,
  actsCount,
  actsSummary,
  targetShareLine,
} from './role-format';

function slice(overrides: Partial<RoleDaySlice> = {}): RoleDaySlice {
  return {
    role_id: 2,
    role_code: 'architect',
    title: 'Системный архитектор',
    minutes: 0,
    share_pct: 0,
    target_share_pct: 25,
    act_count: 0,
    ...overrides,
  };
}

function day(overrides: Partial<RoleDay> = {}): RoleDay {
  return {
    work_day: '2026-08-30',
    total_minutes: 0,
    roles: [slice()],
    blocks: [],
    acts: [],
    ...overrides,
  };
}

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

describe('targetShareLine', () => {
  it('never prints the target without calling it a hypothesis', () => {
    const line = targetShareLine(slice({ target_share_pct: 25 }));
    expect(line).toContain('25%');
    expect(line).toContain(TARGET_SHARE_HYPOTHESIS);
    expect(line).not.toContain('норма ');
  });

  it('says nothing for a role with no target', () => {
    expect(targetShareLine(slice({ target_share_pct: null }))).toBeNull();
  });
});

describe('actsSummary', () => {
  it('says out loud that a day carries no acts', () => {
    expect(actsSummary(day())).toBe(NO_ACTS_TEXT);
  });

  it('names the role of the day that carries one', () => {
    const withAct = day({
      roles: [
        slice({ act_count: 1 }),
        slice({ role_id: 3, role_code: 'techlead', title: 'Тимлид', target_share_pct: 50 }),
      ],
      acts: [ADR_ACT],
    });
    expect(actsSummary(withAct)).toBe('Системный архитектор — 1 акт');
    expect(actsSummary(withAct)).not.toBe(actsSummary(day()));
  });

  it('leaves out the roles that carry none', () => {
    const mixed = day({
      roles: [
        slice({ act_count: 2 }),
        slice({ role_id: 3, role_code: 'techlead', title: 'Тимлид', act_count: 0 }),
      ],
    });
    expect(actsSummary(mixed)).toBe('Системный архитектор — 2 акта');
  });
});

describe('actsCount', () => {
  it('picks the right of the three Russian forms, teens included', () => {
    expect(actsCount(1)).toBe('1 акт');
    expect(actsCount(2)).toBe('2 акта');
    expect(actsCount(5)).toBe('5 актов');
    expect(actsCount(11)).toBe('11 актов');
    expect(actsCount(21)).toBe('21 акт');
  });
});

describe('actKindLabel', () => {
  it('names the kinds the backend vocabulary carries', () => {
    expect(actKindLabel('adr_written')).toBe('написан ADR');
    expect(actKindLabel('budget_decision')).toBe('решение по бюджету');
  });

  it('shows the code of a kind it has not caught up with', () => {
    expect(actKindLabel('board_meeting')).toBe('board_meeting');
  });

  it('offers every named kind in the form', () => {
    expect(ACT_KIND_OPTIONS.length).toBeGreaterThan(0);
    expect(ACT_KIND_OPTIONS.map((option) => option.value)).toContain('adr_written');
    expect(ACT_KIND_OPTIONS.every((option) => option.label.length > 0)).toBe(true);
  });
});

describe('actLine', () => {
  it('reads as the kind and then what it was', () => {
    expect(actLine(ADR_ACT)).toBe('написан ADR: ADR-0020');
  });
});
