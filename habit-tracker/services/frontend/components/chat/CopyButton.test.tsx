// [review:need-review] PHASE-03/120
// summary: tests for the copy button — the clipboard receives the message verbatim, the button says so afterwards, a browser that refuses the clipboard leaves it silent instead of claiming a copy, and the affordance carries the class that keeps it reachable on a touch screen

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import CopyButton, { COPIED_LABEL, COPY_LABEL } from '@/components/chat/CopyButton';

const ANSWER = 'Ты спал 6 ч 40 мин — на час меньше недельной середины.';

/** Подменить буфер обмена на время одного теста. */
function useClipboard(writeText: ReturnType<typeof mock>) {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  });
}

afterEach(cleanup);

describe('CopyButton', () => {
  it('кладёт в буфер текст сообщения дословно', async () => {
    const writeText = mock<(text: string) => Promise<void>>(() => Promise.resolve());
    useClipboard(writeText);
    render(<CopyButton text={ANSWER} />);

    fireEvent.click(screen.getByLabelText(COPY_LABEL));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText.mock.calls[0][0]).toBe(ANSWER);
  });

  it('говорит, что скопировалось', async () => {
    useClipboard(mock<(text: string) => Promise<void>>(() => Promise.resolve()));
    render(<CopyButton text={ANSWER} />);

    fireEvent.click(screen.getByLabelText(COPY_LABEL));

    await waitFor(() => expect(screen.getByLabelText(COPIED_LABEL)).toBeTruthy());
  });

  it('молчит, когда браузер отказал в буфере', async () => {
    // Показать «скопировано» там, где не скопировалось, — худший исход:
    // человек уйдёт вставлять пустоту.
    useClipboard(mock<(text: string) => Promise<void>>(() => Promise.reject(new Error('denied'))));
    render(<CopyButton text={ANSWER} />);

    fireEvent.click(screen.getByLabelText(COPY_LABEL));

    await waitFor(() => expect(screen.getByLabelText(COPY_LABEL)).toBeTruthy());
    expect(screen.queryByLabelText(COPIED_LABEL)).toBeNull();
  });

  it('остаётся доступной там, где наведения не бывает', () => {
    // Правило «видна при наведении» живёт в CSS под `hover: hover`; на тач-экране
    // тот же класс оставляет кнопку видимой. Здесь проверяется, что класс на
    // месте: без него кнопка на телефоне недостижима вовсе.
    useClipboard(mock<(text: string) => Promise<void>>(() => Promise.resolve()));
    render(<CopyButton text={ANSWER} />);

    expect(screen.getByLabelText(COPY_LABEL).className).toContain('copy-affordance');
  });
});
