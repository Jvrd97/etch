// [review:need-review] PHASE-03/87
// summary: component tests for the plan — sections keep the order they were sent, a minimum is drawn as its own line under its task, a task shows its criterion of being done, a label without a column of its own is on the screen, and a line that broke a rule is marked with it rather than hidden or refused

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { PlanItem, PlanSection, PlanViolation } from '@/lib/api';
import { EMPTY_PLAN_TEXT } from '@/lib/plan';
import PlanSections from './PlanSections';

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

const NONE = new Set<string>();

afterEach(() => {
  cleanup();
});

describe('PlanSections', () => {
  it('draws the sections in the order they arrived', () => {
    // The acceptance case: the order on screen is the order that was sent, and
    // the server numbered it — nothing here re-sorts.
    const { container } = render(
      <PlanSections
        sections={[
          section({ id: 's1', title: 'Якоря', kind: 'anchors' }),
          section({ id: 's2', title: 'Работа', kind: 'work' }),
          section({ id: 's3', title: 'Свободный вечер', kind: 'free' }),
        ]}
        overlapping={NONE}
      />
    );

    const headings = Array.from(container.querySelectorAll('h2')).map(
      (node) => node.textContent
    );
    expect(headings).toEqual(['Якоря', 'Работа', 'Свободный вечер']);
  });

  it('draws a minimum as its own line under its task', () => {
    // 29 August: a minimum announced inside a task and without a line of its
    // own does not get done. `#88` gives this line a mark.
    render(
      <PlanSections
        sections={[
          section({
            kind: 'training',
            items: [
              item({
                id: 'parent',
                text_plain: 'Подтягивания 3x5',
                children: [
                  item({
                    id: 'min',
                    parent_id: 'parent',
                    kind: 'minimum',
                    text_plain: 'Улица + один подход',
                  }),
                ],
              }),
            ],
          }),
        ]}
        overlapping={NONE}
      />
    );

    expect(screen.getByText('Улица + один подход')).toBeDefined();
    expect(screen.getByText('минимум')).toBeDefined();
  });

  it('shows the criterion by which a task counts as done', () => {
    render(
      <PlanSections
        sections={[
          section({
            items: [
              item({
                kind: 'task',
                code: 'W1',
                text_plain: 'Ответить Sylvia',
                starts_at: '2026-08-31T07:00:00Z',
                ends_at: '2026-08-31T07:15:00Z',
                done_criterion: 'письмо отправлено, любое из двух',
              }),
            ],
          }),
        ]}
        overlapping={NONE}
      />
    );

    expect(screen.getByText('письмо отправлено, любое из двух')).toBeDefined();
    expect(screen.getByText('W1')).toBeDefined();
  });

  it('shows a label that has no column of its own', () => {
    render(
      <PlanSections
        sections={[
          section({
            kind: 'study',
            items: [item({ extra: { 'Формат': 'аудио' } })],
          }),
        ]}
        overlapping={NONE}
      />
    );

    expect(screen.getByText('Формат:')).toBeDefined();
    expect(screen.getByText('аудио')).toBeDefined();
  });

  it('says why a task is here when it is tied to no quarter goal', () => {
    // The rule "somebody else's urgency is said out loud" only works if the
    // sentence the author had to write is actually on the screen.
    render(
      <PlanSections
        sections={[
          section({
            items: [
              item({
                kind: 'task',
                starts_at: '2026-08-31T07:00:00Z',
                ends_at: '2026-08-31T08:00:00Z',
                done_criterion: 'сделано',
                unlinked_reason: 'просрочено вторые сутки',
              }),
            ],
          }),
        ]}
        overlapping={NONE}
      />
    );

    expect(screen.getByText('просрочено вторые сутки')).toBeDefined();
  });

  it('says so when the plan has no sections at all', () => {
    render(<PlanSections sections={[]} overlapping={NONE} />);

    expect(screen.getByText(EMPTY_PLAN_TEXT)).toBeDefined();
  });
});

describe('PlanSections and the rules a line broke', () => {
  const warn: PlanViolation = {
    id: 11,
    day_date: '2026-09-02',
    rule_code: 'free_evening_empty',
    severity: 'warn',
    origin: 'human',
    detail: { item_ids: ['i1'] },
    created_at: '2026-09-02T10:00:00Z',
  };

  it('marks the line the rule was found on, and still draws it', () => {
    // Машине нарушение блокирует запись, человеку — нет: правка стоит на месте,
    // а рядом с ней написано, какое правило канона она переступила.
    render(
      <PlanSections
        sections={[section({ items: [item({ id: 'i1', text_plain: 'вечерняя задача' })] })]}
        overlapping={NONE}
        violations={new Map([['i1', [warn]]])}
      />
    );

    expect(screen.getByText('вечерняя задача')).toBeTruthy();
    expect(screen.getByText('свободный вечер не расписывается')).toBeTruthy();
  });

  it('says nothing about a line that broke nothing', () => {
    render(
      <PlanSections
        sections={[section({ items: [item({ id: 'i2', text_plain: 'обычный пункт' })] })]}
        overlapping={NONE}
        violations={new Map([['i1', [warn]]])}
      />
    );

    expect(screen.queryByText('свободный вечер не расписывается')).toBeNull();
  });

  it('draws the plan unchanged when no violations are passed at all', () => {
    render(
      <PlanSections
        sections={[section({ items: [item({ text_plain: 'пункт' })] })]}
        overlapping={NONE}
      />
    );

    expect(screen.getByText('пункт')).toBeTruthy();
  });
});
