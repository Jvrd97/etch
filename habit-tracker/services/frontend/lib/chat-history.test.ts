// [review:need-review] PHASE-03/111
// summary: tests for the chat history list — a conversation with no first question is named rather than blank, the feed keeps the server's order inside a day, and the day a conversation started reads as «Сегодня»/«Вчера»/a Russian date

import { describe, expect, it } from 'bun:test';
import type { ChatConversation } from '@/lib/api';
import {
  NO_REPLY_YET,
  UNTITLED_CONVERSATION,
  conversationStamp,
  conversationTitle,
  groupByDay,
} from './chat-history';

const conversation = (
  id: number,
  overrides: Partial<ChatConversation> = {}
): ChatConversation => ({
  id,
  title: `Вопрос ${id}`,
  started_on: '2026-08-31',
  kind: 'general',
  llm_backend: 'cli',
  context_version: 1,
  last_message_at: '2026-08-31T14:32:00',
  archived: false,
  created_at: '2026-08-31T14:30:00',
  usage: {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    message_count: 2,
    latency_ms_median: null,
  },
  ...overrides,
});

describe('conversationTitle', () => {
  it('takes the title the server wrote from the first question', () => {
    expect(conversationTitle(conversation(1, { title: 'сделай план на сегодня' }))).toBe(
      'сделай план на сегодня'
    );
  });

  it('names a conversation nobody has asked anything yet', () => {
    // Заголовок пишет сервер по первой реплике человека, поэтому пустой он
    // ровно у заведённого и брошенного разговора. Пустая строка в списке —
    // это строка, по которой нельзя кликнуть осмысленно.
    expect(conversationTitle(conversation(1, { title: null }))).toBe(
      UNTITLED_CONVERSATION
    );
    expect(conversationTitle(conversation(1, { title: '   ' }))).toBe(
      UNTITLED_CONVERSATION
    );
  });
});

describe('conversationStamp', () => {
  it('shows the wall clock of the last reply', () => {
    expect(
      conversationStamp(conversation(1, { last_message_at: '2026-08-31T09:05:00' }))
    ).toBe('09:05');
  });

  it('says so when the conversation has no reply at all', () => {
    expect(conversationStamp(conversation(1, { last_message_at: null }))).toBe(
      NO_REPLY_YET
    );
  });
});

describe('groupByDay', () => {
  const today = '2026-08-31';

  it('keeps the order the server sent inside a day', () => {
    // Лента приходит отсортированной по `last_message_at`; пересортировать её
    // на экране значило бы завести второй порядок и разойтись с сервером.
    const groups = groupByDay([conversation(3), conversation(2), conversation(1)], today);

    expect(groups).toHaveLength(1);
    expect(groups[0].conversations.map((one) => one.id)).toEqual([3, 2, 1]);
  });

  it('names today, yesterday and everything older by its date', () => {
    const groups = groupByDay(
      [
        conversation(3, { started_on: '2026-08-31' }),
        conversation(2, { started_on: '2026-08-30' }),
        conversation(1, { started_on: '2026-08-14' }),
      ],
      today
    );

    expect(groups.map((group) => group.label)).toEqual([
      'Сегодня',
      'Вчера',
      '14 августа 2026',
    ]);
  });

  it('gives every group a key of its own day', () => {
    // Ключ — день, а не позиция: лента перечитывается после каждого хода, и
    // индекс сделал бы React-ключ, который меняет смысл между рендерами.
    const groups = groupByDay([conversation(1, { started_on: '2026-08-14' })], today);

    expect(groups[0].key).toBe('2026-08-14');
  });

  it('gives a conversation with no day a group rather than a broken key', () => {
    // Сервер день присылает всегда; ключ группы при этом — React-ключ, и
    // `undefined` в нём означает список, тихо переставший различать строки.
    const groups = groupByDay(
      [conversation(1, { started_on: '' } as Partial<ChatConversation>)],
      today
    );

    expect(groups[0].key).toBe('unknown');
    expect(groups[0].label).toBe('Без даты');
  });

  it('holds an empty feed without inventing a group', () => {
    expect(groupByDay([], today)).toEqual([]);
  });
});
