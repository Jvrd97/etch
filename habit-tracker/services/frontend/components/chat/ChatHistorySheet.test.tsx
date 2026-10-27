// [review:need-review] PHASE-03/252
// summary: tests for the phone's history panel — the groups «Сегодня»/«Вчера» stand on the server's day (GET /day-mode), not on the browser's clock, which here is far from it

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { ChatConversation } from '@/lib/api';

// The same four hooks every page test mocks, so a mock left behind in the
// shared registry cannot remove one that a later suite links against.
mock.module('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  usePathname: () => '/m/chat',
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

const { default: ChatHistorySheet } = await import('./ChatHistorySheet');
const api = await import('@/lib/api');

/** A day the runner's own clock is never on, so only the server can have named it. */
const SERVER_DAY = '2026-08-31';
const SERVER_YESTERDAY = '2026-08-30';

const conversation = (id: number, startedOn: string): ChatConversation => ({
  id,
  title: `Вопрос ${id}`,
  started_on: startedOn,
  kind: 'general',
  llm_backend: 'cli',
  context_version: 1,
  last_message_at: `${startedOn}T14:32:00`,
  archived: false,
  created_at: `${startedOn}T14:30:00`,
  usage: {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    message_count: 2,
    latency_ms_median: null,
  },
});

// Written onto the shared clients and put back, so whatever other suites left in the registry stays.
const agent = api.agentAPI as unknown as { dayMode?: () => Promise<unknown> };
const chat = api.chatAPI as unknown as { list?: () => Promise<ChatConversation[]> };
const realDayMode = agent.dayMode;
const realList = chat.list;

beforeEach(() => {
  chat.list = () =>
    Promise.resolve([conversation(2, SERVER_DAY), conversation(1, SERVER_YESTERDAY)]);
});

afterEach(() => {
  cleanup();
  agent.dayMode = realDayMode;
  chat.list = realList;
});

function renderSheet() {
  return render(
    <ChatHistorySheet
      id="history"
      activeId={null}
      onClose={() => {}}
      onDeleted={() => {}}
      deleteBlockedReason={() => null}
    />
  );
}

describe('ChatHistorySheet day', () => {
  it('groups the conversations under today and yesterday of the server', async () => {
    agent.dayMode = () =>
      Promise.resolve({ date: SERVER_DAY, kind: 'work', nocode: false, source: 'schedule' });
    renderSheet();

    expect(await screen.findByText('Сегодня')).toBeDefined();
    expect(screen.getByText('Вчера')).toBeDefined();
  });

  it('moves the groups when the server is a day further on', async () => {
    agent.dayMode = () =>
      Promise.resolve({ date: '2026-09-01', kind: 'work', nocode: false, source: 'schedule' });
    renderSheet();

    expect(await screen.findByText('Вчера')).toBeDefined();
    expect(screen.queryByText('Сегодня')).toBeNull();
  });
});
