// [review:need-review] PHASE-03/112
// summary: unit tests for the header badge — the two modes and their wording, and the cache-read number read from the latest answered turn rather than from the largest one

import { describe, expect, it } from 'bun:test';
import type { ChatMessage } from './api';
import { lastCacheRead, resumeMode } from './chat-resume';

function answer(cacheRead: number | null, seq: number): ChatMessage {
  return {
    id: seq,
    seq,
    role: 'assistant',
    content: 'ответ',
    status: 'complete',
    error_code: null,
    input_tokens: 40,
    output_tokens: 9,
    cache_read_tokens: cacheRead,
    latency_ms: 900,
    model: 'claude',
    created_at: '2026-08-30T10:00:00Z',
  };
}

function question(seq: number): ChatMessage {
  return { ...answer(null, seq), role: 'user', content: 'вопрос' };
}

describe('resumeMode', () => {
  it('names the continuation when the server says a session is there', () => {
    const mode = resumeMode(true);

    expect(mode.kind).toBe('resume');
    expect(mode.label).toBe('Продолжение сессии');
  });

  it('names the rebuild when there is nothing to continue', () => {
    const mode = resumeMode(false);

    expect(mode.kind).toBe('replay');
    expect(mode.label).toBe('Полный пересбор');
    // Пересбор — не поломка: формулировка обязана это говорить.
    expect(mode.hint).toContain('ответ тот же');
  });
});

describe('lastCacheRead', () => {
  it('reads the latest answered turn, not the cheapest one', () => {
    const cached = lastCacheRead([
      question(1),
      answer(21_685, 2),
      question(3),
      answer(30_000, 4),
    ]);

    expect(cached).toBe(30_000);
  });

  it('answers null when the last turn read nothing from cache', () => {
    expect(lastCacheRead([question(1), answer(0, 2)])).toBeNull();
  });

  it('answers null for a conversation nobody has answered yet', () => {
    expect(lastCacheRead([question(1)])).toBeNull();
    expect(lastCacheRead([])).toBeNull();
  });
});
