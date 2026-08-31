// [review:need-review] PHASE-03/142
// summary: component tests for the map of the day — the hours are the server's and not the markup's, an edge the canon does not clock says so, the free evening is shown as an interval nobody fills, and a canon that does not require the evening with the family says that instead of hiding the line

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { DayMap } from '@/lib/api';
import DayMapCard, { FREE_EVENING_TITLE, MAP_TITLE } from './DayMapCard';
import { EDGE_WITHOUT_A_TIME } from '@/lib/day-format';

const MAP: DayMap = {
  rule_set_id: 2,
  edges: [
    { kind: 'wake', label: 'подъём', at: '06:00:00' },
    { kind: 'sport', label: 'спорт', at: null },
    { kind: 'work_start', label: 'старт работы', at: '07:45:00' },
    { kind: 'work_stop', label: 'стоп работы', at: '16:00:00' },
    { kind: 'review', label: 'ревью', at: '15:40:00' },
    { kind: 'bedtime', label: 'отбой', at: '22:30:00' },
  ],
  free_evening: { start: '19:10:00', end: '21:00:00' },
  relationship_evening: { start: '18:30:00', end: '21:00:00' },
  relationship_anchor_required: true,
  work_cap_min: 480,
  work_hard_cap_min: 540,
  overtime_lost_min: 600,
  work_stop_at: '16:00:00',
  max_work_tasks: 4,
  max_study_items: 2,
  anchors: ['подъём', 'спорт', 'relationship'],
  hard_edge_kinds: ['anchor', 'hard_point'],
  workdays: [1, 2, 3, 4, 5],
  days_off: [6, 7],
  nocode_days: [2, 4],
  verdict_reasons: ['overtime', 'anchors', 'tasks'],
};

function show(patch: Partial<DayMap> = {}) {
  render(<DayMapCard map={{ ...MAP, ...patch }} />);
}

describe('DayMapCard', () => {
  afterEach(cleanup);

  it('shows the hours of the rule row, not hours of its own', () => {
    show();

    expect(screen.getByText(MAP_TITLE)).toBeDefined();
    expect(screen.getByTestId('edge-wake').textContent).toContain('06:00');
    expect(screen.getByTestId('edge-review').textContent).toContain('15:40');
    expect(screen.getByTestId('edge-bedtime').textContent).toContain('22:30');
  });

  it('says outright that an edge has no hour rather than inventing one', () => {
    show();

    expect(screen.getByTestId('edge-sport').textContent).toContain(
      EDGE_WITHOUT_A_TIME
    );
  });

  it('shows the free evening as an interval that is deliberately empty', () => {
    show();

    expect(screen.getByText(FREE_EVENING_TITLE)).toBeDefined();
    expect(screen.getByText('19:10-21:00')).toBeDefined();
  });

  it('shows the evening with the family, and says when a canon lifts it', () => {
    show();
    expect(screen.getByText('18:30-21:00 — вечер с близкими')).toBeDefined();

    cleanup();
    show({ relationship_anchor_required: false });
    expect(screen.getByText('не требуется этим каноном')).toBeDefined();
  });

  it('reads the formula of the verdict out in the order of the row', () => {
    show();
    expect(screen.getByText('переработка → якоря → задачи')).toBeDefined();

    cleanup();
    show({ verdict_reasons: ['tasks'] });
    expect(screen.getByText('задачи')).toBeDefined();
  });
});
