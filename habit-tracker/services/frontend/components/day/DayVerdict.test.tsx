// [review:need-review] PHASE-03/90, PHASE-03/143
// summary: component tests for the итог block — a lost day names the condition it failed on rather than "не выигран", an unclosed day offers a form instead of reading as a loss, the closing draft carries only what was filled in and feeds both touches, the prose of a closed day is shown, the override button stays dead until a note is typed and is not offered at all on a day whose verdict arrived as prose, unmeasured work is said out loud, a half-closed day reads «вердикт будет вечером» rather than «не закрыт», and a day closed in one touch says the 15:40 review was skipped

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { DaySummary } from '@/lib/api';
import DayVerdict, {
  BODY_LABEL,
  CLOSE_DAY,
  IMPORTED_VERDICT,
  OVERRIDE_NOTE_LABEL,
  OVERRIDE_SAVE,
  REVIEW_DAY,
  REVIEW_DONE,
  REVIEW_SKIPPED,
  WORK_MINUTES_LABEL,
} from './DayVerdict';
import { VERDICT_LATER } from '@/lib/day-format';

const SUMMARY: DaySummary = {
  day_date: '2026-08-28',
  closed: true,
  stage: 'closed',
  reviewed_at: '2026-08-28T15:40:00+02:00',
  review_skipped: false,
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
  verdict_origin: 'computed',
};

function show(patch: Partial<DaySummary> = {}) {
  render(
    <DayVerdict
      summary={{ ...SUMMARY, ...patch }}
      onClose={() => Promise.resolve()}
      onReview={() => Promise.resolve()}
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
        onReview={() => Promise.resolve()}
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

  it('shows the prose of a closed day instead of hiding it in the database', () => {
    // «Проза итога — половина ценности записи», and until now the screen was
    // not one of the places it could be read.
    show({ body_md: 'что мешало: созвон, который был письмом' });

    expect(
      screen.getByText(/созвон, который был письмом/)
    ).toBeDefined();
  });

  it('sends only the fields the closing form was filled in with', async () => {
    // An empty box is «не сказал»: the server writes what it is given and
    // leaves the rest of the row alone, so a blank must not travel as a null.
    const sent: unknown[] = [];
    render(
      <DayVerdict
        summary={{
          ...SUMMARY,
          closed: false,
          verdict: null,
          verdict_reason: 'not_closed',
          streak_after: null,
        }}
        onClose={(draft) => {
          sent.push(draft);
          return Promise.resolve();
        }}
        onReview={() => Promise.resolve()}
      />
    );

    fireEvent.change(screen.getByLabelText(BODY_LABEL), {
      target: { value: 'ровный день' },
    });
    fireEvent.click(screen.getByText(CLOSE_DAY));

    await waitFor(() => expect(sent).toEqual([{ body_md: 'ровный день' }]));
  });

  it('sends the minutes of work when they were typed', async () => {
    const sent: unknown[] = [];
    render(
      <DayVerdict
        summary={{
          ...SUMMARY,
          closed: false,
          verdict: null,
          verdict_reason: 'not_closed',
          streak_after: null,
        }}
        onClose={(draft) => {
          sent.push(draft);
          return Promise.resolve();
        }}
        onReview={() => Promise.resolve()}
      />
    );

    fireEvent.change(screen.getByLabelText(WORK_MINUTES_LABEL), {
      target: { value: '400' },
    });
    fireEvent.click(screen.getByText(CLOSE_DAY));

    await waitFor(() => expect(sent).toEqual([{ work_minutes: 400 }]));
  });

  it('offers no override on a day whose verdict arrived as prose', () => {
    // Such a row comes back `closed: true`, so it used to land in the override
    // branch — and the click erased the imported prose and moved the day under
    // a recompute by marks it never had. The server answers 409; the screen
    // says why instead of offering a button that cannot work.
    show({ source: 'import', body_md: 'день выигран: улица, спорт, вечер' });

    expect(screen.queryByText(OVERRIDE_SAVE)).toBeNull();
    expect(screen.getByText(IMPORTED_VERDICT)).toBeDefined();
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

  it('offers both touches while the day is not closed', () => {
    // Закрытие идёт в два касания, и оба видны с самого начала: кнопка,
    // которую надо искать, — кнопка, которую не нажмут.
    show({ closed: false, stage: 'open', reviewed_at: null, verdict: null });

    expect(screen.getByText(REVIEW_DAY)).toBeDefined();
    expect(screen.getByText(CLOSE_DAY)).toBeDefined();
  });

  it('reads a half-closed day as "рано", not as a loss', () => {
    show({
      closed: false,
      stage: 'reviewed',
      reviewed_at: '2026-08-28T15:40:00+02:00',
      verdict: null,
      verdict_reason: 'not_closed',
    });

    expect(screen.getByText(VERDICT_LATER)).toBeDefined();
    expect(screen.queryByText('День проигран')).toBeNull();
    expect(screen.queryByText('День не закрыт')).toBeNull();
    // Ревью уже было — кнопка предлагает поправить его, а не завести заново.
    expect(screen.getByText(REVIEW_DONE)).toBeDefined();
  });

  it('sends the 15:40 touch through its own handler', async () => {
    const touches: string[] = [];
    render(
      <DayVerdict
        summary={{ ...SUMMARY, closed: false, stage: 'open', reviewed_at: null }}
        onClose={() => {
          touches.push('final');
          return Promise.resolve();
        }}
        onReview={() => {
          touches.push('review');
          return Promise.resolve();
        }}
      />
    );

    fireEvent.click(screen.getByText(REVIEW_DAY));

    await waitFor(() => expect(touches).toEqual(['review']));
  });

  it('says out loud that a day was closed in one touch', () => {
    show({ closed: true, stage: 'closed', reviewed_at: null, review_skipped: true });

    expect(screen.getByText(REVIEW_SKIPPED)).toBeDefined();
  });

  it('says nothing of the kind about a day that had its review', () => {
    show({ review_skipped: false });

    expect(screen.queryByText(REVIEW_SKIPPED)).toBeNull();
  });

  it('marks a verdict that arrived as prose as carried over, not computed', () => {
    show({ source: 'import', verdict_origin: 'migrated_prose' });

    expect(screen.getByText('из записи')).toBeDefined();
    expect(screen.queryByText('вычислен')).toBeNull();
  });

  it('marks a verdict reached here as computed', () => {
    show({ verdict_origin: 'computed' });

    expect(screen.getByText('вычислен')).toBeDefined();
  });

  it('signs nothing on a day that has no verdict at all', () => {
    show({ closed: false, stage: 'open', verdict: null, verdict_origin: 'none' });

    expect(screen.queryByText('вычислен')).toBeNull();
    expect(screen.queryByText('из записи')).toBeNull();
  });
});
