// [review:need-review] PHASE-03/118
// summary: unit tests for the chat draft — a draft survives a reload of the screen, drafts of two conversations do not leak into each other, an emptied draft leaves no key behind, and a storage that throws (private mode, storage denied) neither loses the typing nor propagates

import { describe, expect, it } from 'bun:test';
import {
  CHAT_DRAFT_KEY_PREFIX,
  chatDraftKey,
  clearChatDraft,
  readChatDraft,
  writeChatDraft,
  type DraftStorage,
} from './chat-draft';

/** In-memory stand-in for localStorage, with the map exposed to assert on. */
function fakeStorage(): DraftStorage & { map: Map<string, string> } {
  const map = new Map<string, string>();
  return {
    map,
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => {
      map.set(key, value);
    },
    removeItem: (key) => {
      map.delete(key);
    },
  };
}

/** Storage of a browser that refuses to store anything at all. */
function refusingStorage(): DraftStorage {
  return {
    getItem: () => {
      throw new Error('storage denied');
    },
    setItem: () => {
      throw new Error('storage denied');
    },
    removeItem: () => {
      throw new Error('storage denied');
    },
  };
}

const CONVERSATION = 7;
const OTHER_CONVERSATION = 8;
const HALF_WRITTEN = 'сегодня сорвалась тренировка, потому что';

describe('chatDraftKey', () => {
  it('names the conversation it belongs to', () => {
    expect(chatDraftKey(CONVERSATION)).toBe(`${CHAT_DRAFT_KEY_PREFIX}${CONVERSATION}`);
    expect(chatDraftKey(CONVERSATION)).not.toBe(chatDraftKey(OTHER_CONVERSATION));
  });
});

describe('readChatDraft', () => {
  it('returns the text a previous session wrote — the whole point of the draft', () => {
    // Приложение свернули на середине реплики: экран смонтирован заново, а
    // хранилище то же самое.
    const storage = fakeStorage();
    writeChatDraft(storage, CONVERSATION, HALF_WRITTEN);

    expect(readChatDraft(storage, CONVERSATION)).toBe(HALF_WRITTEN);
  });

  it('returns an empty string when nothing was ever written', () => {
    expect(readChatDraft(fakeStorage(), CONVERSATION)).toBe('');
  });

  it('does not hand one conversation the draft of another', () => {
    const storage = fakeStorage();
    writeChatDraft(storage, CONVERSATION, HALF_WRITTEN);

    expect(readChatDraft(storage, OTHER_CONVERSATION)).toBe('');
  });

  it('reads an empty string on the server, where there is no storage', () => {
    expect(readChatDraft(null, CONVERSATION)).toBe('');
  });

  it('reads an empty string from a storage that throws instead of answering', () => {
    expect(readChatDraft(refusingStorage(), CONVERSATION)).toBe('');
  });
});

describe('writeChatDraft', () => {
  it('replaces the previous draft rather than appending to it', () => {
    const storage = fakeStorage();
    writeChatDraft(storage, CONVERSATION, 'первый вариант');
    writeChatDraft(storage, CONVERSATION, HALF_WRITTEN);

    expect(readChatDraft(storage, CONVERSATION)).toBe(HALF_WRITTEN);
  });

  it('leaves no key behind when the field is emptied', () => {
    // Иначе localStorage копит по записи на каждый когда-либо открытый
    // разговор, и «очистить черновик» перестаёт что-либо очищать.
    const storage = fakeStorage();
    writeChatDraft(storage, CONVERSATION, HALF_WRITTEN);
    writeChatDraft(storage, CONVERSATION, '');

    expect(storage.map.has(chatDraftKey(CONVERSATION))).toBe(false);
  });

  it('treats whitespace as empty — it is not a message that can be sent', () => {
    const storage = fakeStorage();
    writeChatDraft(storage, CONVERSATION, '   \n  ');

    expect(storage.map.has(chatDraftKey(CONVERSATION))).toBe(false);
  });

  it('keeps the whitespace inside a real draft — the caret sits after it', () => {
    const storage = fakeStorage();
    const trailing = `${HALF_WRITTEN} `;
    writeChatDraft(storage, CONVERSATION, trailing);

    expect(readChatDraft(storage, CONVERSATION)).toBe(trailing);
  });

  it('does not throw when the browser refuses to store — typing must go on', () => {
    expect(() => writeChatDraft(refusingStorage(), CONVERSATION, HALF_WRITTEN)).not.toThrow();
    expect(() => writeChatDraft(null, CONVERSATION, HALF_WRITTEN)).not.toThrow();
  });
});

describe('clearChatDraft', () => {
  it('forgets the draft — what a successful send does', () => {
    const storage = fakeStorage();
    writeChatDraft(storage, CONVERSATION, HALF_WRITTEN);
    clearChatDraft(storage, CONVERSATION);

    expect(readChatDraft(storage, CONVERSATION)).toBe('');
    expect(storage.map.has(chatDraftKey(CONVERSATION))).toBe(false);
  });

  it('leaves the other conversation alone', () => {
    const storage = fakeStorage();
    writeChatDraft(storage, CONVERSATION, HALF_WRITTEN);
    writeChatDraft(storage, OTHER_CONVERSATION, 'другой разговор');
    clearChatDraft(storage, CONVERSATION);

    expect(readChatDraft(storage, OTHER_CONVERSATION)).toBe('другой разговор');
  });

  it('does not throw on a storage that refuses, or on no storage at all', () => {
    expect(() => clearChatDraft(refusingStorage(), CONVERSATION)).not.toThrow();
    expect(() => clearChatDraft(null, CONVERSATION)).not.toThrow();
  });
});
