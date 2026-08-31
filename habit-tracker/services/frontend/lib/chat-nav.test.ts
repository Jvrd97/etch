// [review:need-review] PHASE-03/118
// summary: unit tests for the chat links — a button pressed inside the mobile shell keeps the reader in it, the created conversation travels in the query string, and a hand-edited parameter degrades to "no conversation named" instead of throwing

import { describe, expect, it } from 'bun:test';
import {
  CHAT_CONVERSATION_PARAM,
  CHAT_PATH,
  chatHrefFor,
  chatPathFor,
  conversationIdFrom,
} from './chat-nav';

const CONVERSATION = 42;

describe('chatPathFor', () => {
  it('keeps a reader of the mobile shell inside it', () => {
    expect(chatPathFor('/m/today')).toBe('/m/chat');
    expect(chatPathFor('/m')).toBe('/m/chat');
  });

  it('stays on the desktop route for a desktop screen', () => {
    expect(chatPathFor('/today')).toBe(CHAT_PATH);
    expect(chatPathFor('/')).toBe(CHAT_PATH);
  });

  it('does not mistake a desktop screen whose name starts with m', () => {
    // `/milestones` начинается с той же буквы, что и префикс оболочки;
    // сравнение по префиксу строки без границы сегмента увело бы отсюда в `/m`.
    expect(chatPathFor('/milestones')).toBe(CHAT_PATH);
  });
});

describe('chatHrefFor', () => {
  it('names the conversation to open', () => {
    expect(chatHrefFor('/today', CONVERSATION)).toBe(
      `${CHAT_PATH}?${CHAT_CONVERSATION_PARAM}=${CONVERSATION}`
    );
    expect(chatHrefFor('/m/today', CONVERSATION)).toBe(
      `/m/chat?${CHAT_CONVERSATION_PARAM}=${CONVERSATION}`
    );
  });
});

describe('conversationIdFrom', () => {
  it('reads the id the link carries', () => {
    const params = new URLSearchParams(`${CHAT_CONVERSATION_PARAM}=${CONVERSATION}`);
    expect(conversationIdFrom(params)).toBe(CONVERSATION);
  });

  it('is null when the link names no conversation', () => {
    expect(conversationIdFrom(new URLSearchParams())).toBeNull();
  });

  it('is null for a parameter that is not a positive whole number', () => {
    for (const raw of ['abc', '', '0', '-3', '1.5']) {
      const params = new URLSearchParams(`${CHAT_CONVERSATION_PARAM}=${raw}`);
      expect(conversationIdFrom(params)).toBeNull();
    }
  });
});
