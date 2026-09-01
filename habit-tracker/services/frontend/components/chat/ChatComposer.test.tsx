// [review:need-review] PHASE-03/192
// summary: composer tests — Enter sends, Shift+Enter breaks the line, Enter mid-composition (IME) does not send, and neither a busy turn nor an empty field turns Enter into a send

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import ChatComposer, { ATTACH_LABEL, MESSAGE_FIELD_LABEL } from './ChatComposer';

function renderComposer(
  props: Partial<React.ComponentProps<typeof ChatComposer>> = {}
) {
  const onSend = props.onSend ?? mock(() => {});
  const onChange = props.onChange ?? mock(() => {});
  render(
    <ChatComposer
      value="что сегодня по задачам"
      onChange={onChange}
      onSend={onSend}
      busy={false}
      canSend
      {...props}
    />
  );
  return { onSend, onChange, field: screen.getByLabelText(MESSAGE_FIELD_LABEL) };
}

/** Файл так, как его отдаёт браузер: важен только `name`, `type` и текст. */
function textFile(name: string, text: string, type = 'text/plain'): File {
  return new File([text], name, { type });
}

afterEach(cleanup);

describe('ChatComposer', () => {
  it('sends on Enter', () => {
    const { onSend, field } = renderComposer();

    fireEvent.keyDown(field, { key: 'Enter' });

    expect(onSend).toHaveBeenCalledTimes(1);
  });

  it('leaves Shift+Enter to the line break', () => {
    // Реплика о дне бывает в три абзаца, и способ их набрать обязан остаться.
    const { onSend, field } = renderComposer();

    fireEvent.keyDown(field, { key: 'Enter', shiftKey: true });

    expect(onSend).toHaveBeenCalledTimes(0);
  });

  it('does not send on the Enter that closes an IME composition', () => {
    /*
     * Тот же Enter, которым подтверждают иероглиф или диакритику, отправил бы
     * недописанное слово. Браузер помечает такое нажатие `isComposing`, и это
     * единственный способ их различить.
     */
    const { onSend, field } = renderComposer();

    fireEvent.keyDown(field, { key: 'Enter', isComposing: true });

    expect(onSend).toHaveBeenCalledTimes(0);
  });

  it('ignores Enter while the previous turn is still going', () => {
    const { onSend, field } = renderComposer({ busy: true, canSend: false });

    fireEvent.keyDown(field, { key: 'Enter' });

    expect(onSend).toHaveBeenCalledTimes(0);
  });

  it('ignores Enter on an empty field', () => {
    const { onSend, field } = renderComposer({ value: '', canSend: false });

    fireEvent.keyDown(field, { key: 'Enter' });

    expect(onSend).toHaveBeenCalledTimes(0);
  });

  it('appends a dropped text file to what was typed', async () => {
    const { onChange, field } = renderComposer();

    fireEvent.drop(field.parentElement!.parentElement!, {
      dataTransfer: { files: [textFile('notes.md', 'первая строка')] },
    });

    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    const draft = (onChange as ReturnType<typeof mock>).mock.calls[0][0] as string;
    expect(draft.startsWith('что сегодня по задачам')).toBe(true);
    expect(draft).toContain('notes.md');
    expect(draft).toContain('первая строка');
  });

  it('refuses a binary by name instead of pasting its bytes', async () => {
    const { onChange, field } = renderComposer();

    fireEvent.drop(field.parentElement!.parentElement!, {
      dataTransfer: {
        files: [textFile('photo.png', '\u0000\u0001', 'image/png')],
      },
    });

    await waitFor(() => expect(screen.getByText(/photo\.png/)).toBeDefined());
    expect(onChange).toHaveBeenCalledTimes(0);
  });

  it('offers a way to pick a file without dragging it', () => {
    renderComposer();

    expect(screen.getByLabelText(ATTACH_LABEL)).toBeDefined();
  });
});
