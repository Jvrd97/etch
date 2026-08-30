// [review:need-review] PHASE-03/88
// summary: component tests for the day's notebook — the stored text is what is shown, saving is an explicit act rather than a keystroke, an untouched text cannot be saved, and a refused save says so instead of pretending

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import DayNotebook, {
  NOTEBOOK_SAVE,
  NOTEBOOK_SAVED,
  NOTEBOOK_TITLE,
} from './DayNotebook';

afterEach(() => {
  cleanup();
});

describe('DayNotebook', () => {
  it('shows what the day already has', () => {
    render(<DayNotebook value="утро: тихо" onSave={() => Promise.resolve()} />);

    expect(screen.getByLabelText(NOTEBOOK_TITLE)).toHaveProperty(
      'value',
      'утро: тихо'
    );
  });

  it('saves the whole text, and only when asked', async () => {
    // Per keystroke the day's record would be whatever happened to be typed
    // when the network was quickest; prose is written in pauses.
    const saved: string[] = [];
    render(
      <DayNotebook
        value={null}
        onSave={(content) => {
          saved.push(content);
          return Promise.resolve();
        }}
      />
    );

    fireEvent.change(screen.getByLabelText(NOTEBOOK_TITLE), {
      target: { value: 'вечер: успел' },
    });
    expect(saved).toEqual([]);

    fireEvent.click(screen.getByText(NOTEBOOK_SAVE));

    await waitFor(() => expect(saved).toEqual(['вечер: успел']));
    expect(screen.getByText(NOTEBOOK_SAVED)).toBeDefined();
  });

  it('cannot be saved when nothing was typed', () => {
    render(<DayNotebook value="как есть" onSave={() => Promise.resolve()} />);

    expect(screen.getByText(NOTEBOOK_SAVE)).toHaveProperty('disabled', true);
  });

  it('says when the save failed instead of showing "Сохранено"', async () => {
    render(
      <DayNotebook
        value={null}
        onSave={() => Promise.reject(new Error('сеть отвалилась'))}
      />
    );

    fireEvent.change(screen.getByLabelText(NOTEBOOK_TITLE), {
      target: { value: 'что-то' },
    });
    fireEvent.click(screen.getByText(NOTEBOOK_SAVE));

    await waitFor(() => expect(screen.getByText('сеть отвалилась')).toBeDefined());
    expect(screen.queryByText(NOTEBOOK_SAVED)).toBeNull();
  });
});
