// [review:need-review] PHASE-03/90
// summary: component tests for the итог block — a lost day names the condition it failed on rather than "не выигран", an unclosed day offers to close instead of reading as a loss, the override button stays dead until a note is typed, and unmeasured work is said out loud

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { DaySummary } from '@/lib/api';
import DayVerdict, {
  CLOSE_DAY,
  OVERRIDE_NOTE_LABEL,
  OVERRIDE_SAVE,
} from './DayVerdict';

const SUMMARY: DaySummary = {
  day_date: '2026-08-28',
  closed: true,
  rule_set_id: 2,
  verdict: 'lost',
  verdict_reason: 'tasks',
  verdict_override: false,
  verdict_override_note: null,
  anchors_done: 5,
  anchors_total: 5,
  tasks_done: 3,
  tasks_total: 4,
  work_minutes: 400,
  streak_after: 0,
  wrote_from_scratch: null,
  education_debt: null,
  reviewed_today: null,
  body_md: '',
  missing_data: [],
  missing_anchors: [],
  source: 'close',
};

function show(patch: Partial<DaySummary> = {}) {
  render(
    <DayVerdict
      summary={{ ...SUMMARY, ...patch }}
      onClose={() => Promise.resolve()}
    />
  );
}

afterEach(() => {
  cleanup();
});

describe('DayVerdict', () => {
  it('names the condition that failed rather than "день не выигран"', () => {
    // The acceptance case: 3/4 tasks says «задачи», and the reader knows what
    // to repair without opening the plan.
    show();

    expect(screen.getByText('День проигран')).toBeDefined();
    expect(screen.getByText(/задачи/)).toBeDefined();
    expect(screen.getByText(/3 из 4/)).toBeDefined();
  });

  it('names the anchor that was missed, not only the count', () => {
    show({
      verdict_reason: 'anchors',
      anchors_done: 4,
      missing_anchors: ['Вечер с близкими'],
    });

    expect(screen.getByText('Вечер с близкими')).toBeDefined();
  });

  it('offers to close an unclosed day instead of calling it lost', () => {
    show({
      closed: false,
      verdict: null,
      verdict_reason: 'not_closed',
      streak_after: null,
    });

    expect(screen.getByText('День не закрыт')).toBeDefined();
    expect(screen.queryByText('День проигран')).toBeNull();
    expect(screen.getByText(CLOSE_DAY)).toBeDefined();
  });

  it('says when the work was never measured', () => {
    show({ work_minutes: null, missing_data: ['work_minutes'] });

    expect(screen.getByText('время не измерено')).toBeDefined();
  });

  it('shows the streak in countable Russian', () => {
    show({ verdict: 'won', verdict_reason: '', tasks_done: 4, streak_after: 2 });

    expect(screen.getByText(/2 дня/)).toBeDefined();
  });

  it('keeps the override button dead until a note is written', () => {
    // «Переопределение остаётся видимым действием, а не молчаливой правкой» —
    // and the button is where that is enforced for a person.
    show();

    expect(screen.getByText(OVERRIDE_SAVE)).toHaveProperty('disabled', true);

    fireEvent.change(screen.getByLabelText(OVERRIDE_NOTE_LABEL), {
      target: { value: 'сделал, отметить забыл' },
    });

    expect(screen.getByText(OVERRIDE_SAVE)).toHaveProperty('disabled', false);
  });

  it('sends the note with the override', async () => {
    const sent: unknown[] = [];
    render(
      <DayVerdict
        summary={SUMMARY}
        onClose={(draft) => {
          sent.push(draft);
          return Promise.resolve();
        }}
      />
    );

    fireEvent.change(screen.getByLabelText(OVERRIDE_NOTE_LABEL), {
      target: { value: 'сделал, отметить забыл' },
    });
    fireEvent.click(screen.getByText(OVERRIDE_SAVE));

    await waitFor(() =>
      expect(sent).toEqual([
        {
          verdict_override: true,
          verdict_override_note: 'сделал, отметить забыл',
        },
      ])
    );
  });

  it('keeps the machine reason visible after an override', () => {
    show({
      verdict: 'won',
      verdict_reason: 'tasks',
      verdict_override: true,
      verdict_override_note: 'сделал, отметить забыл',
    });

    expect(screen.getByText('День выигран')).toBeDefined();
    expect(screen.getByText(/задачи/)).toBeDefined();
    expect(screen.getByText(/сделал, отметить забыл/)).toBeDefined();
  });
});
