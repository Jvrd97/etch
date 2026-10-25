// [review:need-review] PHASE-03/200
// summary: component tests for the fact card of a linked plan line — target and fact told apart, a number typed with its unit, a partial fact sent without a tick, a box recorded with one button, a correction that edits the entry it names, a delete that takes two taps, a broken link that offers no input, and the notice after an untick that left history behind

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { MarkState, PlanFactDraft, PlanItemFacts } from '@/lib/api';
import PlanItemFact, {
  ADD_MORE_LABEL,
  CORRECT_LABEL,
  DELETE_FACT_CONFIRM_LABEL,
  DELETE_FACT_LABEL,
  HISTORY_LABEL,
  RECORD_LABEL,
  SAVE_CORRECTION_LABEL,
  UNREADABLE_VALUE,
  UNTICKED_NOTICE,
  WAS_THERE_LABEL,
} from './PlanItemFact';

afterEach(() => {
  cleanup();
});

const ENTRY = {
  entry_id: 7,
  entry_date: '2026-08-31',
  values: [{ field_id: 11, value: '300' }],
  created_at: '2026-08-31T18:00:00Z',
  updated_at: '2026-08-31T18:00:00Z',
};

function pushups(over: Partial<PlanItemFacts> = {}): PlanItemFacts {
  return {
    item_id: 'i1',
    link: {
      category_id: 5,
      category_name: 'Отжимания',
      category_active: true,
      field_id: 11,
      field_name: 'Повторения',
      field_type: 'number',
      unit: 'раз',
      target_value: 300,
      state: 'ok',
      fields: [{ id: 11, name: 'Повторения', field_type: 'number', unit: 'раз' }],
    },
    entries: [],
    total: null,
    done: false,
    progress: 'none',
    ...over,
  };
}

function setup(facts: PlanItemFacts, markState: MarkState | null = null) {
  const recorded: PlanFactDraft[] = [];
  const corrected: Array<[number, PlanFactDraft]> = [];
  const removed: Array<[number, string | null]> = [];
  const view = render(
    <PlanItemFact
      facts={facts}
      markState={markState}
      saving={false}
      error={null}
      onRecord={(draft) => recorded.push(draft)}
      onCorrect={(entryId, draft) => corrected.push([entryId, draft])}
      onRemove={(entryId, mark) => removed.push([entryId, mark])}
    />
  );
  return { recorded, corrected, removed, view };
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe('PlanItemFact', () => {
  it('keeps the target apart from the fact and links to the history', () => {
    setup(pushups());

    expect(screen.getByText('Цель 300 раз, пока не записано')).toBeDefined();
    const link = screen.getByText(HISTORY_LABEL).closest('a');
    expect(link?.getAttribute('href')).toBe('/categories/5');
  });

  it('records 300 with its unit and ticks the line once the target is met', () => {
    const { recorded } = setup(pushups());

    type('Повторения, раз', '300');
    fireEvent.click(screen.getByText(RECORD_LABEL));

    expect(recorded).toEqual([
      { values: [{ field_id: 11, value: 300, unit: 'раз' }], mark: 'done' },
    ]);
  });

  it('sends a partial fact without a tick', () => {
    const { recorded } = setup(pushups());

    type('Повторения, раз', '100');
    fireEvent.click(screen.getByText(RECORD_LABEL));

    expect(recorded).toEqual([{ values: [{ field_id: 11, value: 100, unit: 'раз' }] }]);
  });

  it('refuses to send what is not a number', () => {
    const { recorded } = setup(pushups());

    type('Повторения, раз', 'много');
    fireEvent.click(screen.getByText(RECORD_LABEL));

    expect(recorded).toEqual([]);
    expect(screen.getByText(UNREADABLE_VALUE)).toBeDefined();
  });

  it('records a gym visit with one button', () => {
    const gym = pushups();
    gym.link = {
      ...gym.link,
      category_name: 'Спортзал',
      field_id: 21,
      field_name: 'Посетил',
      field_type: 'boolean',
      unit: null,
      target_value: null,
      fields: [{ id: 21, name: 'Посетил', field_type: 'boolean', unit: null }],
    };
    const { recorded } = setup(gym);

    fireEvent.click(screen.getByText(WAS_THERE_LABEL));

    expect(recorded).toEqual([{ values: [{ field_id: 21, value: true }], mark: 'done' }]);
  });

  it('does not offer a second visit once the box is ticked', () => {
    // One more tap would be a second gym visit in the history; a correction
    // goes through «Исправить», where «Не было» is offered too.
    const gym = pushups({
      entries: [{ ...ENTRY, values: [{ field_id: 21, value: 'true' }] }],
      done: true,
      progress: 'met',
    });
    gym.link = {
      ...gym.link,
      field_id: 21,
      field_name: 'Посетил',
      field_type: 'boolean',
      unit: null,
      target_value: null,
      fields: [{ id: 21, name: 'Посетил', field_type: 'boolean', unit: null }],
    };
    setup(gym, 'done');

    expect(screen.queryByText(WAS_THERE_LABEL, { selector: 'button' })).toBeNull();
    fireEvent.click(screen.getByText(CORRECT_LABEL));
    expect(screen.getByText(WAS_THERE_LABEL, { selector: 'button' })).toBeDefined();
  });

  it('offers «Добавить ещё» once something is recorded', () => {
    setup(pushups({ entries: [ENTRY], total: 300, done: true, progress: 'met' }));

    expect(screen.getByText(ADD_MORE_LABEL)).toBeDefined();
    expect(screen.getByText('Сделано 300 из 300 раз')).toBeDefined();
  });

  it('corrects the entry it names instead of adding one', () => {
    const { corrected, recorded } = setup(
      pushups({ entries: [ENTRY], total: 300, done: true, progress: 'met' }),
      'done'
    );

    fireEvent.click(screen.getByText(CORRECT_LABEL));
    type('Повторения, раз', '200');
    fireEvent.click(screen.getByText(SAVE_CORRECTION_LABEL));

    expect(recorded).toEqual([]);
    expect(corrected).toEqual([
      [7, { values: [{ field_id: 11, value: 200, unit: 'раз' }], mark: 'unmark' }],
    ]);
  });

  it('deletes only on the second tap', () => {
    const { removed } = setup(
      pushups({ entries: [ENTRY], total: 300, done: true, progress: 'met' })
    );

    fireEvent.click(screen.getByText(DELETE_FACT_LABEL));
    expect(removed).toEqual([]);
    fireEvent.click(screen.getByText(DELETE_FACT_CONFIRM_LABEL));

    expect(removed).toEqual([[7, 'unmark']]);
  });

  it('offers no input into a broken link and says why', () => {
    const archived = pushups();
    archived.link = { ...archived.link, state: 'category_archived', category_active: false };
    setup(archived);

    expect(screen.getByText(/в архиве/)).toBeDefined();
    expect(screen.queryByText(RECORD_LABEL)).toBeNull();
  });

  it('says the history stayed after the tick was taken off', () => {
    const recordedFacts = pushups({ entries: [ENTRY], total: 300, done: true, progress: 'met' });
    const { view } = setup(recordedFacts, 'done');
    expect(screen.queryByText(UNTICKED_NOTICE)).toBeNull();

    view.rerender(
      <PlanItemFact
        facts={recordedFacts}
        markState={null}
        saving={false}
        error={null}
        onRecord={() => {}}
        onCorrect={() => {}}
        onRemove={() => {}}
      />
    );

    expect(screen.getByText(UNTICKED_NOTICE)).toBeDefined();
  });

  it('fills the other fields of a composite category in the same entry', () => {
    const workout = pushups();
    workout.link = {
      ...workout.link,
      category_name: 'Тренировка',
      unit: null,
      target_value: null,
      fields: [
        { id: 10, name: 'Подходы', field_type: 'number', unit: null },
        { id: 11, name: 'Повторения', field_type: 'number', unit: null },
        { id: 12, name: 'Время', field_type: 'duration', unit: null },
      ],
    };
    const { recorded } = setup(workout);

    type('Повторения', '120');
    type('Подходы', '4');
    type('Время', '0:30');
    fireEvent.click(screen.getByText(RECORD_LABEL));

    expect(recorded).toEqual([
      {
        values: [
          { field_id: 11, value: 120 },
          { field_id: 10, value: 4 },
          { field_id: 12, value: 1800, unit: 's' },
        ],
        mark: 'done',
      },
    ]);
  });
});
