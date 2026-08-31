// [review:need-review] PHASE-03/138
// summary: tests for the words of the role summary — the gap read with a sign, the target always labelled a hypothesis, the `unassigned` note turning into the ADR-0020 signal above the threshold, and the period boundaries counted from the day the server named rather than from the browser's calendar

import { describe, expect, it } from 'bun:test';
import type { RoleSummary, RoleSummarySlice } from '@/lib/api';
import {
  TARGET_HYPOTHESIS,
  actsText,
  deltaText,
  periodBack,
  summaryMinutes,
  targetText,
  unassignedNote,
  workingRoles,
} from '@/lib/role-share';

function slice(patch: Partial<RoleSummarySlice> = {}): RoleSummarySlice {
  return {
    role_id: 1,
    role_code: 'cto',
    title: 'CTO',
    minutes: 100,
    share_pct: 10,
    target_share_pct: 25,
    delta_pct: -15,
    act_counts: {},
    act_total: 0,
    ...patch,
  };
}

function summary(patch: Partial<RoleSummary> = {}): RoleSummary {
  return {
    date_from: '2026-08-24',
    date_to: '2026-08-30',
    total_minutes: 1000,
    roles: [
      slice(),
      slice({ role_id: 9, role_code: 'unassigned', title: 'Не отнесено', target_share_pct: null, delta_pct: null }),
    ],
    unassigned_minutes: 100,
    unassigned_share_pct: 10,
    window_from: '2026-08-01',
    window_minutes: 5000,
    window_unassigned_share_pct: 10,
    lag_threshold_pct: 30,
    rules_lag: false,
    markdown: '## Роли за период',
    ...patch,
  };
}

describe('deltaText', () => {
  it('отклонение вверх читается со знаком: без него неясно, в какую сторону', () => {
    expect(deltaText(slice({ delta_pct: 12 }))).toBe('+12 п.п.');
  });

  it('отклонение вниз несёт минус', () => {
    expect(deltaText(slice({ delta_pct: -23 }))).toBe('-23 п.п.');
  });

  it('роль без целевой доли отклонения не имеет', () => {
    expect(deltaText(slice({ delta_pct: null }))).toBeNull();
  });
});

describe('targetText', () => {
  it('целевая доля показывается процентом', () => {
    expect(targetText(slice({ target_share_pct: 25 }))).toBe('25%');
  });

  it('у «не отнесено» цели нет и быть не может', () => {
    expect(targetText(slice({ target_share_pct: null }))).toBe('—');
  });

  it('подпись прямо называет целевую долю гипотезой', () => {
    expect(TARGET_HYPOTHESIS).toContain('гипотеза');
    expect(TARGET_HYPOTHESIS).not.toContain('норма квартала');
  });
});

describe('unassignedNote', () => {
  it('ниже порога называет долю и порог, но сигнала не подаёт', () => {
    const text = unassignedNote(summary({ window_unassigned_share_pct: 29 }));

    expect(text).toContain('29%');
    expect(text).toContain('30%');
    expect(text).not.toContain('ADR-0020');
  });

  it('выше порога прямо говорит, что правила разметки отстали', () => {
    const text = unassignedNote(
      summary({ rules_lag: true, window_unassigned_share_pct: 31 })
    );

    expect(text).toContain('правила разметки отстали');
    expect(text).toContain('ADR-0020');
  });

  it('порог берётся из ответа сервера, а не из своего числа', () => {
    const text = unassignedNote(summary({ lag_threshold_pct: 40 }));

    expect(text).toContain('40%');
  });
});

describe('workingRoles', () => {
  it('«не отнесено» идёт своей строкой, а не в общем списке ролей', () => {
    expect(workingRoles(summary()).map((one) => one.role_code)).toEqual(['cto']);
  });
});

describe('actsText', () => {
  it('акты перечисляются по видам: одно число не ловит вырождение в ритуал', () => {
    const text = actsText(
      slice({ act_counts: { adr_written: 4, budget_decision: 1 }, act_total: 5 })
    );

    expect(text).toBe('adr_written × 4, budget_decision × 1');
  });

  it('роль без актов отдаёт пустую строку, а не «0»', () => {
    expect(actsText(slice())).toBe('');
  });
});

describe('summaryMinutes', () => {
  it('минуты читаются часами и минутами', () => {
    expect(summaryMinutes(2400)).toBe('40 ч 0 мин');
  });
});

describe('periodBack', () => {
  it('неделя кончается названным днём и включает его', () => {
    expect(periodBack('2026-08-30', 'week')).toEqual({
      from: '2026-08-24',
      to: '2026-08-30',
    });
  });

  it('месяц — тридцать дней, считая последний', () => {
    expect(periodBack('2026-08-30', 'month')).toEqual({
      from: '2026-08-01',
      to: '2026-08-30',
    });
  });

  it('границы считаются от дня, который назвал сервер', () => {
    // Календарь браузера здесь не участвует вовсе: в 00:30 «сегодня» у него и
    // у приложения разные, а сутки начинаются в 4:00.
    expect(periodBack('2026-01-01', 'week').from).toBe('2025-12-26');
  });
});
