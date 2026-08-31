// [review:need-review] PHASE-03/87, PHASE-03/88
// summary: tests for reading a plan — the duration the server measured is shown as written, both halves of a collision are marked, a section falls back to its kind only when it has no title of its own, and every item is reachable by id at any depth

import { describe, expect, it } from 'bun:test';
import type { Plan, PlanItem, PlanSection, ScheduleOverlap } from '@/lib/api';
import {
  extraLines,
  formatDuration,
  itemKindLabel,
  itemKindsById,
  overlappingItemIds,
  rigidityLabel,
  sectionTitle,
  totalOverlapMinutes,
} from '@/lib/plan';

function item(overrides: Partial<PlanItem> = {}): PlanItem {
  return {
    id: 'i1',
    parent_id: null,
    ord: 0,
    kind: 'bullet',
    rigidity: 'soft',
    text_md: 'пункт',
    text_plain: 'пункт',
    starts_at: null,
    ends_at: null,
    window_comment: null,
    code: null,
    done_criterion: null,
    why_md: null,
    plan_md: null,
    external_ref: null,
    extra: {},
    quarter_goal_id: null,
    unlinked_reason: null,
    carried_from_item_id: null,
    carry_count: 0,
    children: [],
    ...overrides,
  };
}

function section(overrides: Partial<PlanSection> = {}): PlanSection {
  return { id: 's1', ord: 0, title: null, kind: 'work', items: [], ...overrides };
}

function plan(sections: PlanSection[]): Plan {
  return {
    id: 'p1',
    day_date: '2026-08-31',
    title: null,
    title_marker: null,
    lede: null,
    purpose_md: null,
    quarter_goal_id: null,
    counters: [],
    condition_tomorrow: null,
    status: 'active',
    source: 'day-open',
    needs_review: false,
    created_at: '2026-08-31T06:00:00Z',
    updated_at: '2026-08-31T06:00:00Z',
    sections,
    schedule: [],
    overlaps: [],
  };
}

describe('formatDuration', () => {
  it('spells minutes the way the canon itself is written', () => {
    expect(formatDuration(60)).toBe('1 ч');
    expect(formatDuration(90)).toBe('1 ч 30 мин');
    expect(formatDuration(25)).toBe('25 мин');
  });

  it('shows a window across midnight as the hour the server measured', () => {
    // The whole point of taking `minutes` from the server: nothing here knows
    // that the day runs 04:00 to 04:00, and nothing here has to.
    expect(formatDuration(60)).toBe('1 ч');
  });
});

describe('overlappingItemIds', () => {
  const overlaps: ScheduleOverlap[] = [
    { left_item_id: 'a', right_item_id: 'b', overlap_minutes: 60 },
    { left_item_id: 'b', right_item_id: 'c', overlap_minutes: 15 },
  ];

  it('marks both halves of every collision', () => {
    // A highlight on only one of the two would read as "this line is wrong",
    // when the fact is that two lines claim the same minute.
    const ids = overlappingItemIds(overlaps);

    expect(ids.has('a')).toBe(true);
    expect(ids.has('b')).toBe(true);
    expect(ids.has('c')).toBe(true);
  });

  it('leaves a line that collides with nothing alone', () => {
    expect(overlappingItemIds(overlaps).has('d')).toBe(false);
  });

  it('adds up how much of the day is claimed twice', () => {
    expect(totalOverlapMinutes(overlaps)).toBe(75);
  });
});

describe('sectionTitle', () => {
  it("keeps the author's own heading", () => {
    expect(sectionTitle(section({ title: 'Воскресный блок' }))).toBe(
      'Воскресный блок'
    );
  });

  it('falls back to the kind when the section arrived without a title', () => {
    expect(sectionTitle(section({ kind: 'hard_points' }))).toBe(
      'Жёсткие точки дня'
    );
  });

  it('does not treat a blank title as a title', () => {
    expect(sectionTitle(section({ title: '   ', kind: 'training' }))).toBe(
      'Тренировка'
    );
  });
});

describe('labels', () => {
  it('says nothing about an item that simply moves', () => {
    // `soft` is the default and the normal case; a badge on every line would
    // be noise where the exceptions are the point.
    expect(rigidityLabel('soft')).toBeNull();
    expect(rigidityLabel('hard')).toBe('жёстко');
    expect(rigidityLabel('free')).toBe('свободно');
  });

  it('names the kinds that carry meaning and no others', () => {
    expect(itemKindLabel('task')).toBe('задача');
    expect(itemKindLabel('minimum')).toBe('минимум');
    expect(itemKindLabel('bullet')).toBeNull();
  });
});

describe('itemKindsById', () => {
  it('reaches every item, at any depth', () => {
    // The header counts tasks against their marks, and marks are keyed by item
    // id — so the kind of a nested line has to be reachable by id too. A
    // minimum inside a training block is exactly such a line.
    const nested = item({
      id: 'parent',
      children: [item({ id: 'child', kind: 'task' })],
    });
    const counted = plan([
      section({
        items: [item({ id: 'a', kind: 'task' }), item({ id: 'b', kind: 'anchor' }), nested],
      }),
    ]);

    const kinds = itemKindsById(counted);

    expect(kinds.size).toBe(4);
    expect([...kinds.values()].filter((kind) => kind === 'task')).toHaveLength(2);
    expect(kinds.get('child')).toBe('task');
  });

  it('answers with nothing for a day that has no plan', () => {
    expect(itemKindsById(null).size).toBe(0);
  });
});

describe('extraLines', () => {
  it('reads back a label that has no column of its own', () => {
    // The acceptance case, on the screen half: `Формат :: аудио` survives the
    // round trip and is visible, not merely preserved.
    const lines = extraLines(item({ extra: { 'Формат': 'аудио' } }));

    expect(lines).toEqual([{ label: 'Формат', value: 'аудио' }]);
  });

  it('shows a non-string value rather than dropping it', () => {
    const lines = extraLines(item({ extra: { Счётчики: [1, 2] } }));

    expect(lines[0].value).toBe('[1,2]');
  });
});
