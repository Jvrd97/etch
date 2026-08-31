// [review:need-review] PHASE-03/111
// summary: history tests — conversations stand under the day they started, the open one is marked for a screen reader too, the row links into the shell the reader is already in, «Новый разговор» is one click that cannot fire twice, and an unread history says so instead of looking empty

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ChatConversation } from '@/lib/api';
import ChatHistory, {
  EMPTY_HISTORY,
  NEW_CONVERSATION,
} from '@/components/chat/ChatHistory';

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

const TODAY = '2026-08-31';

function renderHistory(props: Partial<React.ComponentProps<typeof ChatHistory>> = {}) {
  return render(
    <ChatHistory
      conversations={[conversation(2), conversation(1, { started_on: '2026-08-30' })]}
      activeId={2}
      today={TODAY}
      hrefFor={(id) => `/chat?conversation=${id}`}
      onStart={() => {}}
      {...props}
    />
  );
}

afterEach(cleanup);

describe('ChatHistory', () => {
  it('puts every conversation under the day it started', () => {
    renderHistory();

    expect(screen.getByText('Сегодня')).toBeDefined();
    expect(screen.getByText('Вчера')).toBeDefined();
    expect(screen.getByText('Вопрос 2')).toBeDefined();
    expect(screen.getByText('Вопрос 1')).toBeDefined();
  });

  it('marks the open conversation for a screen reader, not only by colour', () => {
    renderHistory();

    const open = screen.getByRole('link', { current: 'page' });
    expect(open.textContent).toContain('Вопрос 2');
  });

  it('links into the shell the reader is already in', () => {
    // Ссылку строит вызывающий: кнопка на `/m/chat` обязана вести на `/m/chat`,
    // а не выкидывать из мобильной оболочки.
    renderHistory({ hrefFor: (id) => `/m/chat?conversation=${id}` });

    const row = screen.getByRole('link', { name: /Вопрос 1/ });
    expect(row.getAttribute('href')).toBe('/m/chat?conversation=1');
  });

  it('names a conversation nobody asked anything and says it has no replies', () => {
    renderHistory({
      conversations: [conversation(5, { title: null, last_message_at: null })],
      activeId: 5,
    });

    expect(screen.getByText('Разговор без вопроса')).toBeDefined();
    expect(screen.getByText(/без реплик/)).toBeDefined();
  });

  it('starts a new conversation on one click', () => {
    const onStart = mock(() => {});
    renderHistory({ onStart });

    fireEvent.click(screen.getByRole('button', { name: NEW_CONVERSATION }));

    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it('cannot start two conversations while one is being created', () => {
    const onStart = mock(() => {});
    renderHistory({ onStart, starting: true });

    const button = screen.getByRole('button', { name: NEW_CONVERSATION });
    fireEvent.click(button);

    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(onStart).not.toHaveBeenCalled();
  });

  it('says an empty history is empty', () => {
    renderHistory({ conversations: [], activeId: null });

    expect(screen.getByText(EMPTY_HISTORY)).toBeDefined();
  });

  it('tells a failed read apart from an empty history', () => {
    // «Разговоров нет» и «список не прочитался» — разные ответы, и второй не
    // имеет права выглядеть первым.
    renderHistory({ conversations: [], activeId: null, error: '502: бэкенд молчит' });

    expect(screen.getByText(/502/)).toBeDefined();
    expect(screen.queryByText(EMPTY_HISTORY)).toBeNull();
  });
});
