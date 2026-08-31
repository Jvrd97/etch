// [review:need-review] PHASE-03/139
// summary: component tests for the rule form and the re-markup panel — the dry run shown before anything is saved, an empty history read as «нечего было прогонять» rather than «правило не ловит», the rule a match is taken from named by its pattern, and the re-markup panel saying how many confirmed rows it left alone

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type {
  Role,
  RoleReclassified,
  RoleRule,
  RoleRuleDraft,
  RoleRuleDryRun,
} from '@/lib/api';
import RoleRuleForm from '@/components/RoleRuleForm';
import RoleReclassifyPanel from '@/components/RoleReclassifyPanel';
import { NOTHING_TO_SCAN } from '@/lib/role-rules';

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
  {
    id: 2,
    code: 'cto',
    title: 'CTO',
    description: null,
    target_share_pct: 25,
    is_work: true,
    ord: 1,
    is_active: true,
  },
];

const EXISTING: RoleRule[] = [
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

function run(patch: Partial<RoleRuleDryRun> = {}): RoleRuleDryRun {
  return {
    date_from: '2026-08-01',
    date_to: '2026-08-30',
    scanned_rows: 120,
    matched_time_blocks: 12,
    matched_acts: 3,
    taken_from: { '7': 9 },
    taken_from_nobody: 6,
    examples: [
      {
        kind: 'time_block',
        work_day: '2026-08-30',
        label: 'feat(api): ручка',
        current_role_id: 2,
        taken_from_rule_id: 7,
      },
    ],
    ...patch,
  };
}

afterEach(cleanup);

describe('RoleRuleForm', () => {
  it('прогон показывает счётчики до того, как что-то сохранено', async () => {
    const saved: RoleRuleDraft[] = [];
    render(
      <RoleRuleForm
        roles={ROLES}
        rules={EXISTING}
        onDryRun={async () => run()}
        onSave={async (draft) => {
          saved.push(draft);
        }}
      />
    );

    fireEvent.change(screen.getByLabelText('Образец'), {
      target: { value: 'feat(' },
    });
    fireEvent.click(screen.getByTestId('dry-run'));

    await waitFor(() => screen.getByTestId('dry-run-result'));
    const result = screen.getByTestId('dry-run-result');
    expect(result.textContent).toContain('интервалов: 12');
    expect(result.textContent).toContain('актов: 3');
    expect(saved).toEqual([]);
  });

  it('прогон называет правило, у которого отбирает совпадения, образцом', async () => {
    render(
      <RoleRuleForm
        roles={ROLES}
        rules={EXISTING}
        onDryRun={async () => run()}
        onSave={async () => {}}
      />
    );

    fireEvent.change(screen.getByLabelText('Образец'), {
      target: { value: 'feat(' },
    });
    fireEvent.click(screen.getByTestId('dry-run'));

    await waitFor(() => screen.getByTestId('dry-run-result'));
    expect(screen.getByTestId('dry-run-result').textContent).toContain('«chore(»');
  });

  it('пустая история читается как «прогонять не по чему», а не «не ловит»', async () => {
    render(
      <RoleRuleForm
        roles={ROLES}
        rules={EXISTING}
        onDryRun={async () =>
          run({ scanned_rows: 0, matched_time_blocks: 0, matched_acts: 0, examples: [] })
        }
        onSave={async () => {}}
      />
    );

    fireEvent.change(screen.getByLabelText('Образец'), {
      target: { value: 'feat(' },
    });
    fireEvent.click(screen.getByTestId('dry-run'));

    await waitFor(() => screen.getByTestId('dry-run-result'));
    expect(screen.getByTestId('dry-run-result').textContent).toContain(NOTHING_TO_SCAN);
  });

  it('правило заводится с экрана — форма шлёт то, что человек набрал', async () => {
    const saved: RoleRuleDraft[] = [];
    render(
      <RoleRuleForm
        roles={ROLES}
        rules={EXISTING}
        onDryRun={async () => run()}
        onSave={async (draft) => {
          saved.push(draft);
        }}
      />
    );

    fireEvent.change(screen.getByLabelText('Образец'), {
      target: { value: 'feat(' },
    });
    fireEvent.change(screen.getByLabelText('Вес'), { target: { value: '10' } });
    fireEvent.click(screen.getByTestId('save-rule'));

    await waitFor(() => expect(saved.length).toBe(1));
    expect(saved[0]).toEqual({
      role_code: 'techlead',
      source: 'app_usage',
      matcher_kind: 'commit_prefix',
      pattern: 'feat(',
      priority: 10,
    });
  });

  it('пустой образец не даёт ни прогнать, ни сохранить', () => {
    render(
      <RoleRuleForm
        roles={ROLES}
        rules={EXISTING}
        onDryRun={async () => run()}
        onSave={async () => {}}
      />
    );

    expect(screen.getByTestId('dry-run').hasAttribute('disabled')).toBe(true);
    expect(screen.getByTestId('save-rule').hasAttribute('disabled')).toBe(true);
  });
});

const RECLASSIFIED: RoleReclassified = {
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
    { role_id: 2, minutes: 200, share_pct: 20 },
  ],
};

describe('RoleReclassifyPanel', () => {
  it('показывает «до/после» долей и число нетронутых записей', async () => {
    render(
      <RoleReclassifyPanel
        roles={ROLES}
        defaultFrom="2026-08-01"
        defaultTo="2026-08-30"
        onReclassify={async () => RECLASSIFIED}
      />
    );

    fireEvent.click(screen.getByTestId('reclassify'));

    await waitFor(() => screen.getByTestId('reclassify-result'));
    expect(screen.getByTestId('reclassify-protected').textContent).toContain(
      'не тронуто: 5'
    );
    const result = screen.getByTestId('reclassify-result');
    expect(result.textContent).toContain('Тимлид: 0% → 80%');
    expect(result.textContent).toContain('CTO: 100% → 20%');
  });

  it('период передаётся тем, что стоит в полях', async () => {
    const asked: string[][] = [];
    render(
      <RoleReclassifyPanel
        roles={ROLES}
        defaultFrom="2026-08-01"
        defaultTo="2026-08-30"
        onReclassify={async (from, to) => {
          asked.push([from, to]);
          return RECLASSIFIED;
        }}
      />
    );

    fireEvent.change(screen.getByLabelText('С'), { target: { value: '2026-07-01' } });
    fireEvent.click(screen.getByTestId('reclassify'));

    await waitFor(() => expect(asked.length).toBe(1));
    expect(asked[0]).toEqual(['2026-07-01', '2026-08-30']);
  });
});
