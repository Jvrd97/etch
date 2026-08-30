// [review:need-review] PHASE-03/93
// summary: component tests for the goal board — six levels, ten milestones and five goals of the quarter are on the screen, and the chip by which M10 waits for M9 reads differently once M9 is closed

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { GoalsPayload, Milestone, MilestoneStatus } from '@/lib/api';

function milestone(code: string, overrides: Partial<Milestone> = {}): Milestone {
  return {
    code,
    title: `Милстон ${code}`,
    done_criterion: 'сделано',
    when_text: 'сейчас',
    ord: Number(code.slice(1)),
    status: 'open',
    done_on: null,
    depends_on: [],
    ...overrides,
  };
}

const PAYLOAD: GoalsPayload = {
  levels: [0, 1, 2, 3, 4, 5].map((level) => ({
    level,
    title: `уровень ${level}`,
    body_md: '',
    open_questions: level === 0 ? ['⚠ подтверди: какой из двух главный'] : [],
  })),
  milestones: [
    ...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => milestone(`M${n}`)),
    milestone('M9'),
    milestone('M10', { depends_on: ['M8', 'M9'] }),
  ],
  quarter: '2026-Q3',
  goals: [1, 2, 3, 4, 5].map((ord) => ({
    id: ord,
    quarter: '2026-Q3',
    ord,
    text_md: `**Цель ${ord}**`,
    milestone_code: null,
    status: 'open',
  })),
};

let state: {
  payload: GoalsPayload | null;
  loading: boolean;
  error: string | null;
  saving: Set<string>;
  markMilestone: (code: string, status: MilestoneStatus) => void;
};

mock.module('@/hooks/useGoals', () => ({
  useGoals: () => state,
  LOAD_GOALS_ERROR: 'Не удалось загрузить цели',
}));

const { default: GoalsBoard, OPENED_LABEL, WAITING_LABEL } = await import('./GoalsBoard');

function closedM9(): GoalsPayload {
  return {
    ...PAYLOAD,
    milestones: PAYLOAD.milestones.map((one) =>
      one.code === 'M9' ? { ...one, status: 'done', done_on: '2026-08-30' } : one
    ),
  };
}

beforeEach(() => {
  state = {
    payload: PAYLOAD,
    loading: false,
    error: null,
    saving: new Set<string>(),
    markMilestone: () => {},
  };
});

afterEach(() => {
  cleanup();
});

describe('GoalsBoard', () => {
  it('shows six levels, ten milestones and five goals of the quarter', () => {
    // The first acceptance case, from the side a person sees it.
    render(<GoalsBoard />);

    for (const level of [0, 1, 2, 3, 4, 5]) {
      expect(screen.getByText(`Уровень ${level} — уровень ${level}`)).toBeDefined();
    }
    for (let n = 1; n <= 10; n += 1) {
      expect(screen.getByText(`M${n} · Милстон M${n}`)).toBeDefined();
    }
    for (const ord of [1, 2, 3, 4, 5]) {
      // The bold of `goal.md` is stripped: a reader sees the words, not `**`.
      expect(screen.getByText(`${ord}. Цель ${ord}`)).toBeDefined();
    }
  });

  it('keeps the ⚠ подтверди line visible rather than folded into the prose', () => {
    render(<GoalsBoard />);

    expect(screen.getByText('⚠ подтверди: какой из двух главный')).toBeDefined();
  });

  it('changes how M10 shows its dependency once M9 is closed', () => {
    // The fifth acceptance case: closing M9 is not a fact about M9 alone.
    render(<GoalsBoard />);
    expect(screen.getByText(`M9 · ${WAITING_LABEL}`)).toBeDefined();
    cleanup();

    state = { ...state, payload: closedM9() };
    render(<GoalsBoard />);

    expect(screen.getByText(`M9 · ${OPENED_LABEL}`)).toBeDefined();
    // M8 is still open, so the other chip of M10 is unchanged.
    expect(screen.getByText(`M8 · ${WAITING_LABEL}`)).toBeDefined();
  });

  it('shows the date a closed milestone was closed on', () => {
    state = { ...state, payload: closedM9() };

    render(<GoalsBoard />);

    expect(screen.getByText('закрыт · 2026-08-30')).toBeDefined();
  });

  it('says so when the goals have not been imported yet', () => {
    state = { ...state, payload: null };

    render(<GoalsBoard />);

    expect(screen.getByText(/goal\.md/)).toBeDefined();
  });
});
