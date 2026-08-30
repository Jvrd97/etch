// [review:need-review] PHASE-03/116
// summary: tests for how the feed draws a stored turn by its status — an interrupted answer keeps the text that did arrive under a note, a failed one is spelled out from its machine code, an unclosed `streaming` row says so and carries the button that unsticks the dialogue, and a complete answer carries no note at all

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import ChatFeed, { RESET_LABEL } from '@/components/chat/ChatFeed';
import { MESSAGE_STATUS_NOTE, TURN_ERROR_TEXT } from '@/hooks/useChat';
import type { ChatMessage } from '@/lib/api';

const HALF_ANSWER = 'начал отвечать и не дого';

function message(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: 1,
    seq: 2,
    role: 'assistant',
    content: HALF_ANSWER,
    status: 'complete',
    error_code: null,
    input_tokens: null,
    output_tokens: null,
    cache_read_tokens: null,
    latency_ms: null,
    model: null,
    created_at: '2026-08-31T10:00:00Z',
    ...overrides,
  } as ChatMessage;
}

afterEach(cleanup);

describe('ChatFeed: a stored turn by its status', () => {
  it('keeps the text an interrupted answer did manage to send', () => {
    render(
      <ChatFeed
        messages={[message({ status: 'interrupted' })]}
        turn={{ phase: 'idle' }}
        emptyHint="пусто"
      />
    );

    // То, что успело прийти, человек уже читал: отнимать это из-за закрытой
    // вкладки не за что — поэтому текст на месте, а пометка объясняет обрыв.
    expect(screen.getByText(HALF_ANSWER)).toBeTruthy();
    expect(screen.getByText(MESSAGE_STATUS_NOTE.interrupted)).toBeTruthy();
  });

  it('spells out a failed turn from its machine code', () => {
    render(
      <ChatFeed
        messages={[message({ status: 'failed', error_code: 'first_delta_timeout' })]}
        turn={{ phase: 'idle' }}
        emptyHint="пусто"
      />
    );

    expect(screen.getByText(TURN_ERROR_TEXT.first_delta_timeout)).toBeTruthy();
  });

  it('offers the reset only on a turn nobody is going to close', () => {
    const onReset = mock(() => undefined);
    render(
      <ChatFeed
        messages={[message({ status: 'streaming' })]}
        turn={{ phase: 'idle' }}
        emptyHint="пусто"
        onReset={onReset}
      />
    );

    expect(screen.getByText(MESSAGE_STATUS_NOTE.streaming)).toBeTruthy();
    fireEvent.click(screen.getByText(RESET_LABEL));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it('says nothing extra about an answer that finished', () => {
    render(
      <ChatFeed
        messages={[message({})]}
        turn={{ phase: 'idle' }}
        emptyHint="пусто"
        onReset={() => undefined}
      />
    );

    expect(screen.queryByText(RESET_LABEL)).toBeNull();
    expect(screen.queryByText(MESSAGE_STATUS_NOTE.interrupted)).toBeNull();
  });
});
