// [review:need-review] PHASE-03/92
// summary: component tests for the training block — the minimum says whether it has a tick of its own, the run of skipped days is visible, an open complaint stands beside the offer and the movement it removed is named with its reason

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { TrainingDay, TrainingState } from '@/lib/api';
import DayTraining, {
  COMPLAINTS_TITLE,
  RECORDS_TITLE,
  EXCLUDED_TITLE,
  MINIMUM_HAS_ITEM,
  MINIMUM_NO_ITEM,
  SKIPPED_DAYS_TITLE,
  TRAINING_EMPTY,
} from './DayTraining';

const TRAINING: TrainingDay = {
  day_date: '2026-08-30',
  patterns: ['pull'],
  heavy_patterns: [],
  planned_md: 'только pull: подтягивания 3x5 RIR 2',
  done_md: null,
  skipped: false,
  outdoor_done: null,
  near_failure: false,
  note_md: null,
  minimum_md: 'улица + разминка + один подход',
  minimum_item_id: null,
  sets: {},
};

const STATE: TrainingState = {
  as_of: '2026-08-30',
  last_heavy_pull: '2026-08-17',
  last_heavy_push: '2026-08-28',
  last_legs: '2026-08-12',
  last_run: '2026-08-11',
  last_outdoor: '2026-08-28',
  last_cardio: '2026-08-13',
  near_failure_days: [],
  week_sets: { pull: 4, push: 8 },
  progression_stage: {},
  skipped_days: 2,
  recomputed_at: '2026-08-30T18:00:00+00:00',
  open_complaints: [],
  records: [],
  suggestion: {
    exercises: ['австралийские тяги', 'планка'],
    excluded: [],
    gates: [],
    rir: 'RIR 3',
    volume_factor: 0.7,
  },
};

afterEach(() => {
  cleanup();
});

describe('DayTraining', () => {
  it('says a day with nothing recorded is empty rather than a skip', () => {
    render(<DayTraining training={null} state={null} />);

    expect(screen.getByText(TRAINING_EMPTY)).toBeDefined();
  });

  it('shows what was planned, what was done and the minimum', () => {
    render(
      <DayTraining
        training={{ ...TRAINING, done_md: 'улица 15 минут' }}
        state={null}
      />
    );

    expect(screen.getByText(/только pull/)).toBeDefined();
    expect(screen.getByText('улица 15 минут')).toBeDefined();
    expect(screen.getByText('улица + разминка + один подход')).toBeDefined();
  });

  it('warns when the minimum has no tick of its own', () => {
    // 29 августа: минимум без своей галки не выполняется. Блок говорит об этом
    // прямо, а не оставляет читателя проверять план глазами.
    render(<DayTraining training={TRAINING} state={null} />);

    expect(screen.getByText(MINIMUM_NO_ITEM)).toBeDefined();
  });

  it('says when the minimum does have its own plan item', () => {
    render(
      <DayTraining
        training={{ ...TRAINING, minimum_item_id: 'item-1' }}
        state={null}
      />
    );

    expect(screen.getByText(MINIMUM_HAS_ITEM)).toBeDefined();
  });

  it('shows the run of skipped days', () => {
    // Приёмка тикета: два пропуска подряд видны на странице.
    render(<DayTraining training={TRAINING} state={STATE} />);

    expect(screen.getByText(`${SKIPPED_DAYS_TITLE}: 2`)).toBeDefined();
  });

  it('puts the open complaint next to the offer', () => {
    render(
      <DayTraining
        training={TRAINING}
        state={{
          ...STATE,
          open_complaints: [
            {
              id: 'c1',
              opened_on: '2026-08-10',
              area: 'левое плечо',
              context: null,
              severity: 'кольнуло, прошло',
              status: 'open',
              closed_on: null,
              closed_reason: null,
            },
          ],
          suggestion: {
            ...STATE.suggestion,
            excluded: [
              {
                exercise: 'подтягивания',
                gate: 'complaint',
                reason: 'открытая жалоба «левое плечо»',
              },
            ],
          },
        }}
      />
    );

    expect(screen.getByText(COMPLAINTS_TITLE)).toBeDefined();
    expect(screen.getByText(/левое плечо — с 2026-08-10/)).toBeDefined();
    expect(screen.getByText(EXCLUDED_TITLE)).toBeDefined();
    expect(screen.getByText('подтягивания')).toBeDefined();
    expect(screen.getByText(/открытая жалоба/)).toBeDefined();
  });

  it('shows a personal record with its date and its target', () => {
    // Приёмка тикета: рекорд виден с датой достижения и целью.
    render(
      <DayTraining
        training={TRAINING}
        state={{
          ...STATE,
          records: [
            {
              id: 'r1',
              exercise: 'подтягивания',
              variant: null,
              sets: '9/10/5/3',
              best_plain: null,
              achieved_on: '2026-08-10',
              target: '4x8 RIR 1-2',
            },
          ],
        }}
      />
    );

    expect(screen.getByText(RECORDS_TITLE)).toBeDefined();
    expect(screen.getByText(/подтягивания: 9\/10\/5\/3/)).toBeDefined();
    expect(screen.getByText(/2026-08-10, цель: 4x8 RIR 1-2/)).toBeDefined();
  });

  it('names the intensity the gates left the day at', () => {
    render(<DayTraining training={TRAINING} state={STATE} />);

    expect(screen.getByText(/RIR 3/)).toBeDefined();
  });

  it('marks a skipped day as skipped', () => {
    render(
      <DayTraining training={{ ...TRAINING, skipped: true }} state={null} />
    );

    expect(screen.getByText('Пропуск')).toBeDefined();
  });
});
