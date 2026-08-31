// [review:need-review] PHASE-03/117
// summary: tests of the spend wording — grouping is locale-independent, a zero is printed rather than hidden, a latency under a second stays in milliseconds, and a message without counters gets no line at all

import { describe, expect, it } from 'bun:test';
import type { ChatMessage, ChatUsage } from '@/lib/api';
import { formatLatency, formatTokens, turnCost, usageSummary } from '@/lib/chat-usage';

const EMPTY_USAGE: ChatUsage = {
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  message_count: 0,
  latency_ms_median: null,
};

function message(fields: Partial<ChatMessage>): ChatMessage {
  return {
    id: 1,
    seq: 1,
    role: 'assistant',
    content: 'ответ',
    status: 'complete',
    error_code: null,
    input_tokens: null,
    output_tokens: null,
    cache_read_tokens: null,
    latency_ms: null,
    model: null,
    created_at: '2026-08-30T10:00:00Z',
    ...fields,
  };
}

describe('formatTokens', () => {
  it('groups by three with a plain space, whatever the locale of the machine', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(999)).toBe('999');
    expect(formatTokens(1200)).toBe('1 200');
    expect(formatTokens(52555)).toBe('52 555');
    expect(formatTokens(1234567)).toBe('1 234 567');
  });
});

describe('formatLatency', () => {
  it('stays in milliseconds below a second and turns into seconds above it', () => {
    expect(formatLatency(820)).toBe('820 мс');
    expect(formatLatency(1000)).toBe('1,0 с');
    expect(formatLatency(4200)).toBe('4,2 с');
  });

  it('has nothing to say when nothing was measured', () => {
    expect(formatLatency(null)).toBeNull();
  });
});

describe('usageSummary', () => {
  it('prints a zero rather than an empty header', () => {
    expect(usageSummary(EMPTY_USAGE)).toBe('вход 0 · выход 0 · из кеша 0');
  });

  it('names all three counters and the median when there is one', () => {
    expect(
      usageSummary({
        input_tokens: 1200,
        output_tokens: 300,
        cache_read_tokens: 52555,
        message_count: 4,
        latency_ms_median: 4000,
      })
    ).toBe('вход 1 200 · выход 300 · из кеша 52 555 · медиана 4,0 с');
  });
});

describe('turnCost', () => {
  it('says nothing about a message that carries no counters', () => {
    expect(turnCost(message({ role: 'user', content: 'вопрос' }))).toBeNull();
  });

  it('shows what one turn cost, so a cheaper second turn is visible', () => {
    const first = turnCost(
      message({ input_tokens: 1200, output_tokens: 300, cache_read_tokens: 0, latency_ms: 4200 })
    );
    const second = turnCost(
      message({
        input_tokens: 40,
        output_tokens: 260,
        cache_read_tokens: 1500,
        latency_ms: 900,
      })
    );

    expect(first).toBe('вход 1 200 · выход 300 · из кеша 0 · 4,2 с');
    expect(second).toBe('вход 40 · выход 260 · из кеша 1 500 · 900 мс');
  });

  it('fills a missing counter with zero once any of the three is there', () => {
    expect(turnCost(message({ input_tokens: 10 }))).toBe('вход 10 · выход 0 · из кеша 0');
  });
});
