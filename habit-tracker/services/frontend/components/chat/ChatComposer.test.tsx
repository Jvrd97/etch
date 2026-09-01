// [review:need-review] PHASE-03/192
// summary: composer tests — Enter sends, Shift+Enter breaks the line, Enter mid-composition (IME) does not send, and neither a busy turn nor an empty field turns Enter into a send

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import ChatComposer, { MESSAGE_FIELD_LABEL } from './ChatComposer';

function renderComposer(
  props: Partial<React.ComponentProps<typeof ChatComposer>> = {}
) {
  const onSend = props.onSend ?? mock(() => {});
  render(
    <ChatComposer
      value="что сегодня по задачам"
      onChange={() => {}}
      onSend={onSend}
      busy={false}
      canSend
      {...props}
    />
  );
  return { onSend, field: screen.getByLabelText(MESSAGE_FIELD_LABEL) };
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
});
