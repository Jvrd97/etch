// [review:need-review] PHASE-03/117
// summary: header tests — the three counters are on screen, one click deletes nothing until the question is answered, and the confirming button goes unavailable while the request is in flight so a double click cannot send two deletes

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ChatUsage } from '@/lib/api';
import ChatHeader from '@/components/chat/ChatHeader';

const USAGE: ChatUsage = {
  input_tokens: 1200,
  output_tokens: 300,
  cache_read_tokens: 52555,
  message_count: 4,
  latency_ms_median: 4000,
};

afterEach(cleanup);

describe('ChatHeader', () => {
  it('shows all three counters and the median of the dialogue', () => {
    render(
      <ChatHeader
        usage={USAGE}
        state="idle"
        onAsk={() => {}}
        onCancel={() => {}}
        onConfirm={() => {}}
      />
    );

    expect(screen.getByTestId('chat-usage').textContent).toBe(
      'Расход подписки: вход 1 200 · выход 300 · из кеша 52 555 · медиана 4,0 с'
    );
  });

  it('asks before deleting instead of deleting on the first click', () => {
    const onAsk = mock(() => {});
    const onConfirm = mock(() => {});
    render(
      <ChatHeader
        usage={USAGE}
        state="idle"
        onAsk={onAsk}
        onCancel={() => {}}
        onConfirm={onConfirm}
      />
    );

    fireEvent.click(screen.getByLabelText('Удалить разговор'));

    expect(onAsk).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('names what the delete takes with it, not just "delete"', () => {
    render(
      <ChatHeader
        usage={USAGE}
        state="confirming"
        onAsk={() => {}}
        onCancel={() => {}}
        onConfirm={() => {}}
      />
    );

    expect(
      screen.getByText('Удалить разговор вместе с сообщениями и файлом сессии?')
    ).toBeDefined();
  });

  it('sends the delete only from the confirming button', () => {
    const onConfirm = mock(() => {});
    const onCancel = mock(() => {});
    render(
      <ChatHeader
        usage={USAGE}
        state="confirming"
        onAsk={() => {}}
        onCancel={onCancel}
        onConfirm={onConfirm}
      />
    );

    fireEvent.click(screen.getByText('Отмена'));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('cannot be pressed a second time while the request is in flight', () => {
    const onConfirm = mock(() => {});
    render(
      <ChatHeader
        usage={USAGE}
        state="deleting"
        onAsk={() => {}}
        onCancel={() => {}}
        onConfirm={onConfirm}
      />
    );

    const button = screen.getByText('Удаляю…') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
