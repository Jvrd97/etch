// [review:need-review] PHASE-03/111
// summary: unit tests for the chat SSE parser — frames split across chunks, event order preserved, usage/done/error mapped to the union, unknown names and broken JSON skipped rather than thrown on

import { describe, expect, it } from 'bun:test';
import { ChatStreamParser } from './chat-stream';

function frame(name: string, payload: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(payload)}\n\n`;
}

describe('ChatStreamParser', () => {
  it('reads deltas in the order they arrived', () => {
    const parser = new ChatStreamParser();

    const events = parser.push(
      frame('delta', { text: 'Пер' }) + frame('delta', { text: 'вый' })
    );

    expect(events).toEqual([
      { kind: 'delta', text: 'Пер' },
      { kind: 'delta', text: 'вый' },
    ]);
  });

  it('holds a frame split across two chunks until it is whole', () => {
    // The reason this class has state: TCP ends a chunk wherever it likes.
    const parser = new ChatStreamParser();
    const whole = frame('delta', { text: 'ответ' });
    const cut = Math.floor(whole.length / 2);

    expect(parser.push(whole.slice(0, cut))).toEqual([]);
    expect(parser.push(whole.slice(cut))).toEqual([{ kind: 'delta', text: 'ответ' }]);
  });

  it('keeps newlines inside the answer intact', () => {
    const parser = new ChatStreamParser();

    const events = parser.push(frame('delta', { text: 'первая\n\nвторая' }));

    expect(events).toEqual([{ kind: 'delta', text: 'первая\n\nвторая' }]);
  });

  it('maps usage to numbers and missing counters to null', () => {
    const parser = new ChatStreamParser();

    const events = parser.push(
      frame('usage', { input_tokens: 282, output_tokens: 17, cache_read_tokens: null })
    );

    expect(events).toEqual([
      { kind: 'usage', inputTokens: 282, outputTokens: 17, cacheReadTokens: null },
    ]);
  });

  it('maps done to the id of the stored message', () => {
    const parser = new ChatStreamParser();

    const events = parser.push(
      frame('done', { message_id: 7, seq: 2, status: 'complete' })
    );

    expect(events).toEqual([{ kind: 'done', messageId: 7, seq: 2, status: 'complete' }]);
  });

  it('maps error to its machine code', () => {
    const parser = new ChatStreamParser();

    const events = parser.push(frame('error', { code: 'backend_failed' }));

    expect(events).toEqual([{ kind: 'error', code: 'backend_failed' }]);
  });

  it('skips an event name it does not know', () => {
    // The server may grow a `plan` event before this screen learns to draw one;
    // an unknown name must not stop the turn.
    const parser = new ChatStreamParser();

    const events = parser.push(
      frame('plan', { id: 1 }) + frame('delta', { text: 'ок' })
    );

    expect(events).toEqual([{ kind: 'delta', text: 'ок' }]);
  });

  it('skips a frame whose data is not JSON', () => {
    const parser = new ChatStreamParser();

    expect(parser.push('event: delta\ndata: {broken\n\n')).toEqual([]);
  });

  it('skips a done frame missing its message id', () => {
    const parser = new ChatStreamParser();

    expect(parser.push(frame('done', { seq: 2, status: 'complete' }))).toEqual([]);
  });

  it('tolerates CRLF line endings', () => {
    const parser = new ChatStreamParser();

    const events = parser.push('event: delta\r\ndata: {"text":"ок"}\r\n\n');

    expect(events).toEqual([{ kind: 'delta', text: 'ок' }]);
  });

  it('flush returns a last frame that arrived without its blank line', () => {
    const parser = new ChatStreamParser();
    parser.push('event: done\ndata: {"message_id":3,"seq":2,"status":"complete"}');

    expect(parser.flush()).toEqual([
      { kind: 'done', messageId: 3, seq: 2, status: 'complete' },
    ]);
  });

  it('flush on an empty buffer returns nothing', () => {
    const parser = new ChatStreamParser();
    parser.push(frame('delta', { text: 'ок' }));

    expect(parser.flush()).toEqual([]);
  });
});
