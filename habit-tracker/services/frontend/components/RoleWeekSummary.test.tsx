// [review:need-review] PHASE-03/138
// summary: component tests for the role summary block — the target labelled a hypothesis on screen, `unassigned` on its own row saying the threshold, the 31% case naming the ADR-0020 signal while 29% stays silent, an empty period rendering words instead of zeros, and the copy button handing over the server's finished text

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { RoleSummary } from '@/lib/api';
import RoleWeekSummary from '@/components/RoleWeekSummary';
import { COPY_DONE, TARGET_HYPOTHESIS } from '@/lib/role-share';

const MARKDOWN = [
  '## Роли за период 2026-08-24 — 2026-08-30',
  '',
  'Всего за период: 40 ч 0 мин.',
].join('\n');

function summary(patch: Partial<RoleSummary> = {}): RoleSummary {
  return {
    date_from: '2026-08-24',
    date_to: '2026-08-30',
    total_minutes: 2400,
    roles: [
      {
        role_id: 1,
        role_code: 'architect',
        title: 'Системный архитектор',
        minutes: 40,
        share_pct: 2,
        target_share_pct: 25,
        delta_pct: -23,
        act_counts: { adr_written: 5 },
        act_total: 5,
      },
      {
        role_id: 9,
        role_code: 'unassigned',
        title: 'Не отнесено',
        minutes: 200,
        share_pct: 8,
        target_share_pct: null,
        delta_pct: null,
        act_counts: {},
        act_total: 0,
      },
    ],
    unassigned_minutes: 200,
    unassigned_share_pct: 8,
    window_from: '2026-08-01',
    window_minutes: 5000,
    window_unassigned_share_pct: 8,
    lag_threshold_pct: 30,
    rules_lag: false,
    markdown: MARKDOWN,
    ...patch,
  };
}

afterEach(cleanup);

describe('RoleWeekSummary', () => {
  it('перекос видно числом: сорок минут архитектуры из сорока часов', () => {
    render(<RoleWeekSummary summary={summary()} />);

    const roles = screen.getByTestId('summary-roles');
    expect(roles.textContent).toContain('0 ч 40 мин');
    expect(roles.textContent).toContain('2%');
    expect(roles.textContent).toContain('-23 п.п.');
  });

  it('целевая доля подписана на экране гипотезой', () => {
    render(<RoleWeekSummary summary={summary()} />);

    expect(screen.getByTestId('target-note').textContent).toBe(TARGET_HYPOTHESIS);
  });

  it('«не отнесено» стоит своей строкой, а не в общем списке ролей', () => {
    render(<RoleWeekSummary summary={summary()} />);

    expect(screen.getByTestId('summary-roles').textContent).not.toContain(
      'Не отнесено'
    );
    expect(screen.getByTestId('summary-unassigned').textContent).toContain(
      'Не отнесено'
    );
  });

  it('на 29% за тридцать дней экран молчит про правила', () => {
    render(
      <RoleWeekSummary summary={summary({ window_unassigned_share_pct: 29 })} />
    );

    expect(screen.getByTestId('unassigned-note').textContent).not.toContain(
      'отстали'
    );
  });

  it('на 31% экран прямо говорит, что правила разметки отстали', () => {
    render(
      <RoleWeekSummary
        summary={summary({ rules_lag: true, window_unassigned_share_pct: 31 })}
      />
    );

    const note = screen.getByTestId('unassigned-note');
    expect(note.textContent).toContain('правила разметки отстали');
    expect(note.textContent).toContain('ADR-0020');
  });

  it('акты перечислены по видам рядом с долей', () => {
    render(<RoleWeekSummary summary={summary()} />);

    expect(screen.getByTestId('summary-roles').textContent).toContain(
      'adr_written × 5'
    );
  });

  it('период без записей открывается словами, а не нулями', () => {
    render(
      <RoleWeekSummary summary={summary({ total_minutes: 0, roles: [] })} />
    );

    expect(screen.getByTestId('summary-empty')).toBeDefined();
    expect(screen.queryByTestId('summary-roles')).toBeNull();
  });

  it('кнопка кладёт в буфер готовый текст сервера, а не собранный здесь', async () => {
    const written: string[] = [];
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          written.push(text);
        },
      },
    });

    render(<RoleWeekSummary summary={summary()} />);
    fireEvent.click(screen.getByTestId('copy-report'));

    await waitFor(() =>
      expect(screen.getByTestId('copy-report').textContent).toContain(COPY_DONE)
    );
    expect(written).toEqual([MARKDOWN]);
  });

  it('готовый блок виден на экране до всякого копирования', () => {
    render(<RoleWeekSummary summary={summary()} />);

    expect(screen.getByTestId('report-markdown').textContent).toBe(MARKDOWN);
  });
});
