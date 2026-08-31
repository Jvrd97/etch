// [review:need-review] PHASE-03/139
// summary: tests for the words of the rules screen — the empty scan said apart from a rule that catches nothing, the source of a taken match named by its pattern, roles whose share did not move kept out of the before/after, and the default month counted from the day the server named

import { describe, expect, it } from 'bun:test';
import type { Role, RoleReclassified, RoleRule, RoleRuleDryRun } from '@/lib/api';
import {
  NOTHING_TO_SCAN,
  defaultRange,
  dryRunSummary,
  protectedLine,
  reclassifyLines,
  takenFromLines,
} from '@/lib/role-rules';

const RULES: RoleRule[] = [
  {
    id: 7,
    role_id: 2,
    role_code: 'cto',
    source: 'git',
    matcher_kind: 'commit_prefix',
    pattern: 'chore(',
    priority: 50,
    is_active: true,
  },
];

const ROLES: Role[] = [
  {
    id: 1,
    code: 'techlead',
    title: 'Тимлид',
    description: null,
    target_share_pct: 50,
    is_work: true,
    ord: 3,
    is_active: true,
  },
];

function run(patch: Partial<RoleRuleDryRun> = {}): RoleRuleDryRun {
  return {
    date_from: '2026-08-01',
    date_to: '2026-08-30',
    scanned_rows: 120,
    matched_time_blocks: 12,
    matched_acts: 3,
    taken_from: { '7': 9 },
    taken_from_nobody: 6,
    examples: [],
    ...patch,
  };
}

describe('dryRunSummary', () => {
  it('нулевая история и правило, которое не ловит, читаются по-разному', () => {
    expect(dryRunSummary(run({ scanned_rows: 0 }))).toBe(NOTHING_TO_SCAN);
    expect(
      dryRunSummary(run({ matched_time_blocks: 0, matched_acts: 0 }))
    ).toContain('из 120 строк');
  });

  it('интервалы и акты названы двумя числами, а не одним', () => {
    const text = dryRunSummary(run());

    expect(text).toContain('интервалов: 12');
    expect(text).toContain('актов: 3');
  });
});

describe('takenFromLines', () => {
  it('правило называется своим образцом, а не id', () => {
    expect(takenFromLines(run(), RULES)[0]).toContain('«chore(»');
  });

  it('правило, которого нет в списке, называется хотя бы номером', () => {
    expect(takenFromLines(run(), [])[0]).toContain('правило 7');
  });

  it('ничьи совпадения — отдельная строка: это чистое улучшение', () => {
    expect(takenFromLines(run(), RULES).at(-1)).toContain('Ничьих совпадений: 6');
  });

  it('правило, которое ни у кого не отбирает, лишних строк не рисует', () => {
    expect(takenFromLines(run({ taken_from: {}, taken_from_nobody: 0 }), RULES)).toEqual(
      []
    );
  });
});

const RESULT: RoleReclassified = {
  date_from: '2026-08-01',
  date_to: '2026-08-30',
  scanned_rows: 40,
  changed_time_blocks: 12,
  changed_acts: 2,
  protected: 5,
  before: [
    { role_id: 1, minutes: 0, share_pct: 0 },
    { role_id: 2, minutes: 1000, share_pct: 100 },
  ],
  after: [
    { role_id: 1, minutes: 800, share_pct: 80 },
    { role_id: 2, minutes: 1000, share_pct: 100 },
  ],
};

describe('reclassifyLines', () => {
  it('роль, у которой доля не сдвинулась, в отчёт не попадает', () => {
    const lines = reclassifyLines(RESULT, ROLES);

    expect(lines).toEqual(['Тимлид: 0% → 80%']);
  });

  it('роль без названия в справочнике всё равно называется', () => {
    const lines = reclassifyLines(RESULT, []);

    expect(lines[0]).toContain('роль 1');
  });
});

describe('protectedLine', () => {
  it('число подтверждённых записей названо вслух', () => {
    expect(protectedLine(RESULT)).toContain('не тронуто: 5');
  });
});

describe('defaultRange', () => {
  it('месяц кончается днём, который назвал сервер, и включает его', () => {
    expect(defaultRange('2026-08-30')).toEqual({
      from: '2026-08-01',
      to: '2026-08-30',
    });
  });
});
