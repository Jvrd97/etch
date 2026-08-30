// [review:need-review] PHASE-03/88
// summary: component tests for the mark box — a click asks for the next state on the ring, `skipped` is its own deliberate button, and the «как прошло» note appears only once a line has a mark

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import PlanItemMark, { NOTE_PLACEHOLDER, SKIP_LABEL } from './PlanItemMark';
import { MARK_LABEL, MARK_PENDING_LABEL, nextMarkState } from '@/lib/marks';

afterEach(() => {
  cleanup();
});

/** Renders the control and records what it asked for. */
function setup(state: Parameters<typeof PlanItemMark>[0]['state'], note = '') {
  const cycled: string[] = [];
  const states: (string | null)[] = [];
  const notes: string[] = [];

  render(
    <PlanItemMark
      itemId="i1"
      state={state}
      note={note}
      onCycle={(id) => cycled.push(id)}
      onSetState={(_id, next) => states.push(next)}
      onSetNote={(_id, value) => notes.push(value)}
    />
  );

  return { cycled, states, notes };
}

describe('PlanItemMark', () => {
  it('says what state the line is in', () => {
    setup(null);

    expect(screen.getByLabelText(MARK_PENDING_LABEL)).toBeDefined();
  });

  it('asks for a cycle on a click, whatever the state', () => {
    // The screen does not decide the next state — the ring does, in one place
    // (`nextMarkState`), and this button only says "one click happened".
    const { cycled } = setup('done');

    fireEvent.click(screen.getByLabelText(MARK_LABEL.done));

    expect(cycled).toEqual(['i1']);
    expect(nextMarkState('done')).toBe('failed');
  });

  it('keeps «стало неактуально» off the ring and on its own button', () => {
    const { states } = setup(null);

    fireEvent.click(screen.getByText(SKIP_LABEL));

    expect(states).toEqual(['skipped']);
  });

  it('takes a line back off `skipped` with the same button', () => {
    const { states } = setup('skipped');

    fireEvent.click(screen.getByText(SKIP_LABEL));

    expect(states).toEqual([null]);
  });

  it('offers the note only where there is a mark to hang it on', () => {
    // The note lives on the mark row; a field on an unmarked line would have
    // nowhere to save to, and a field that loses what is typed into it is
    // worse than no field.
    setup(null);

    expect(screen.queryByLabelText(NOTE_PLACEHOLDER)).toBeNull();
  });

  it('writes the note when the field is left, and not on every keystroke', () => {
    const { notes } = setup('done', 'старое');

    const field = screen.getByLabelText(NOTE_PLACEHOLDER);
    fireEvent.change(field, { target: { value: 'вышло дольше' } });
    expect(notes).toEqual([]);

    fireEvent.blur(field);
    expect(notes).toEqual(['вышло дольше']);
  });

  it('does not write a note that did not change', () => {
    const { notes } = setup('done', 'как есть');

    fireEvent.blur(screen.getByLabelText(NOTE_PLACEHOLDER));

    expect(notes).toEqual([]);
  });
});
