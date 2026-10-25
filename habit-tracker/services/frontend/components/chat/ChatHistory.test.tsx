// [review:need-review] PHASE-03/111, PHASE-03/203, PHASE-03/197
// summary: PHASE-03/197 covers deleting from the list — an always-visible action on every row that never opens the conversation, a confirmation naming the row (also an unnamed one), cancel sending nothing, one request however many clicks, a failure that keeps the row and offers the retry, a running answer explained instead of hidden, and the date group disappearing with its last row
// summary: PHASE-03/203 adds the states the phone panel needs — a list still being read is not an empty one, a failed read offers a retry, a picked row reports itself so the panel can close
// summary: history tests — conversations stand under the day they started, the open one is marked for a screen reader too, the row links into the shell the reader is already in, «Новый разговор» is one click that cannot fire twice, and an unread history says so instead of looking empty

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { ChatConversation } from '@/lib/api';
import type { RemoveOutcome } from '@/hooks/useChatHistory';
import ChatHistory, {
  EMPTY_HISTORY,
  HISTORY_LOADING,
  HISTORY_RETRY,
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

  it('does not call a list still being read empty', () => {
    // Пустая история до первого ответа сервера — ложь про разговоры, которые
    // есть: человек успевает прочитать «ещё нет» и закрыть панель.
    renderHistory({ conversations: [], activeId: null, loading: true });

    expect(screen.getByText(HISTORY_LOADING)).toBeDefined();
    expect(screen.queryByText(EMPTY_HISTORY)).toBeNull();
  });

  it('offers to read a failed list again', () => {
    const onRetry = mock(() => {});
    renderHistory({ conversations: [], activeId: null, error: '502', onRetry });

    fireEvent.click(screen.getByRole('button', { name: HISTORY_RETRY }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('tells the caller which row was picked', () => {
    // Панель на телефоне закрывается выбором строки — и тогда, когда выбран
    // уже открытый разговор и адрес не меняется.
    const onPick = mock(() => {});
    renderHistory({ onPick });

    fireEvent.click(screen.getByRole('link', { name: /Вопрос 2/ }));

    expect(onPick).toHaveBeenCalledWith(2);
  });
});

const WARNING = /История сообщений исчезнет/;

/**
 * Список с настоящей связкой «удалили — строка ушла», какую даёт
 * `useChatHistory`: без неё нельзя проверить, что пустая группа дня исчезает.
 */
function Harness({
  onDelete,
  blockedReason,
  removing,
}: {
  onDelete: (id: number) => Promise<RemoveOutcome>;
  blockedReason?: (id: number) => string | null;
  removing?: number | null;
}) {
  const [rows, setRows] = useState([
    conversation(3),
    conversation(2, { title: null, last_message_at: null }),
    conversation(1, { started_on: '2026-08-30' }),
  ]);
  return (
    <ChatHistory
      conversations={rows}
      activeId={3}
      today={TODAY}
      hrefFor={(id) => `/chat?conversation=${id}`}
      onStart={() => {}}
      onDelete={async (id) => {
        const outcome = await onDelete(id);
        if (outcome.ok) setRows((current) => current.filter((one) => one.id !== id));
        return outcome;
      }}
      deleteBlockedReason={blockedReason}
      removing={removing}
    />
  );
}

const deleteButton = (title: string) =>
  screen.getByRole('button', { name: `Удалить разговор «${title}»` });

/** Подтверждение, открытое у строки: его группа названа вопросом. */
const confirmation = (title: string) =>
  screen.getByRole('group', { name: new RegExp(`Удалить разговор «${title}»\\?`) });

describe('ChatHistory: deleting a conversation', () => {
  it('offers the delete on every row, always visible and not only on hover', () => {
    render(<Harness onDelete={async () => ({ ok: true })} />);

    for (const title of ['Вопрос 3', 'Разговор без вопроса', 'Вопрос 1']) {
      const button = deleteButton(title) as HTMLButtonElement;
      expect(button.tagName).toBe('BUTTON');
      expect(button.disabled).toBe(false);
      expect(button.className).not.toMatch(/opacity-0|invisible|hidden|group-hover/);
      // Палец, а не курсор: цель не меньше 44 px.
      expect(button.style.minHeight).toBe('44px');
      expect(button.style.minWidth).toBe('44px');
    }
  });

  it('asks first, naming the row and the loss, and does not open the conversation', () => {
    const onDelete = mock(async () => ({ ok: true }) as RemoveOutcome);
    const onPick = mock(() => {});
    renderHistory({ onDelete, onPick });

    fireEvent.click(deleteButton('Вопрос 1'));

    const box = confirmation('Вопрос 1');
    expect(within(box).getByText(WARNING)).toBeDefined();
    expect(within(box).getByRole('button', { name: 'Удалить' })).toBeDefined();
    expect(within(box).getByRole('button', { name: 'Отмена' })).toBeDefined();
    expect(onDelete).not.toHaveBeenCalled();
    expect(onPick).not.toHaveBeenCalled();
  });

  it('puts keyboard focus on the safe choice and gives it back on cancel', () => {
    const onDelete = mock(async () => ({ ok: true }) as RemoveOutcome);
    renderHistory({ onDelete });
    const trigger = deleteButton('Вопрос 1');
    trigger.focus();
    fireEvent.click(trigger);

    const cancel = within(confirmation('Вопрос 1')).getByRole('button', { name: 'Отмена' });
    expect(document.activeElement).toBe(cancel);

    fireEvent.click(cancel);

    expect(screen.queryByRole('group') === null).toBe(true);
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.getByText('Вопрос 1')).toBeDefined();
    expect(document.activeElement).toBe(trigger);
  });

  it('shows the display name when the conversation has no question', () => {
    render(<Harness onDelete={async () => ({ ok: true })} />);

    fireEvent.click(deleteButton('Разговор без вопроса'));

    expect(confirmation('Разговор без вопроса').textContent).toContain('Разговор без вопроса');
  });

  it('deletes after the confirmation, drops the row and the date group with it', async () => {
    const onDelete = mock(async () => ({ ok: true }) as RemoveOutcome);
    render(<Harness onDelete={onDelete} />);
    expect(screen.getByText('Вчера')).toBeDefined();

    fireEvent.click(deleteButton('Вопрос 1'));
    await act(async () => {
      fireEvent.click(within(confirmation('Вопрос 1')).getByRole('button', { name: 'Удалить' }));
    });

    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith(1);
    expect(screen.queryByText('Вопрос 1') === null).toBe(true);
    // Группа «Вчера» держалась на одной строке и ушла вместе с ней.
    expect(screen.queryByText('Вчера') === null).toBe(true);
    expect(screen.getByText('Сегодня')).toBeDefined();
    expect(screen.queryByRole('group') === null).toBe(true);
    expect(screen.getByRole('status').textContent).toContain('Вопрос 1');
  });

  it('sends one request however many times the button is hit', async () => {
    let release: (outcome: RemoveOutcome) => void = () => {};
    const onDelete = mock(
      () =>
        new Promise<RemoveOutcome>((resolve) => {
          release = resolve;
        })
    );
    render(<Harness onDelete={onDelete} />);
    fireEvent.click(deleteButton('Вопрос 1'));
    const confirmButton = within(confirmation('Вопрос 1')).getByRole('button', {
      name: 'Удалить',
    });

    await act(async () => {
      fireEvent.click(confirmButton);
      fireEvent.click(confirmButton);
    });

    expect(onDelete).toHaveBeenCalledTimes(1);
    const pending = within(confirmation('Вопрос 1')).getByRole('button', { name: 'Удаляю…' });
    expect((pending as HTMLButtonElement).disabled).toBe(true);
    // Пока одно удаляется, второе не начать ни из какой строки.
    expect(deleteButton('Вопрос 3').getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(deleteButton('Вопрос 3'));
    expect(screen.queryByRole('group', { name: /Вопрос 3/ }) === null).toBe(true);

    await act(async () => {
      release({ ok: true });
    });
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it('keeps the row on a failure, says why, and lets the delete be repeated', async () => {
    const onDelete = mock(
      async (): Promise<RemoveOutcome> => ({ ok: false, message: 'Не удалось удалить: 500' })
    );
    render(<Harness onDelete={onDelete} />);
    fireEvent.click(deleteButton('Вопрос 1'));
    await act(async () => {
      fireEvent.click(within(confirmation('Вопрос 1')).getByRole('button', { name: 'Удалить' }));
    });

    const box = confirmation('Вопрос 1');
    expect(within(box).getByRole('alert').textContent).toContain('Не удалось удалить: 500');
    expect(screen.getByText('Вопрос 1')).toBeDefined();
    expect(screen.getByText('Вчера')).toBeDefined();

    onDelete.mockImplementation(async () => ({ ok: true }));
    await act(async () => {
      fireEvent.click(within(box).getByRole('button', { name: 'Удалить ещё раз' }));
    });

    expect(onDelete).toHaveBeenCalledTimes(2);
    expect(screen.queryByText('Вопрос 1') === null).toBe(true);
  });

  it('forgets an old failure when another row is asked about', async () => {
    const onDelete = mock(
      async (): Promise<RemoveOutcome> => ({ ok: false, message: 'Не удалось удалить: 500' })
    );
    render(<Harness onDelete={onDelete} />);
    fireEvent.click(deleteButton('Вопрос 1'));
    await act(async () => {
      fireEvent.click(within(confirmation('Вопрос 1')).getByRole('button', { name: 'Удалить' }));
    });

    fireEvent.click(deleteButton('Вопрос 3'));

    expect(screen.queryByRole('alert') === null).toBe(true);
    expect(screen.getAllByRole('group')).toHaveLength(1);
  });

  it('explains a running answer instead of offering a delete that cannot work', () => {
    const onDelete = mock(async () => ({ ok: true }) as RemoveOutcome);
    render(
      <Harness
        onDelete={onDelete}
        blockedReason={(id) => (id === 3 ? 'Ответ ещё идёт — удалить можно после него.' : null)}
      />
    );

    const blocked = deleteButton('Вопрос 3');
    expect(blocked.getAttribute('aria-disabled')).toBe('true');
    const reason = screen.getByText('Ответ ещё идёт — удалить можно после него.');
    expect(blocked.getAttribute('aria-describedby')).toBe(reason.id);

    fireEvent.click(blocked);

    expect(screen.queryByRole('group') === null).toBe(true);
    expect(onDelete).not.toHaveBeenCalled();
    expect(deleteButton('Вопрос 1').getAttribute('aria-disabled')).toBeNull();
  });

  it('will not confirm a delete once the answer has started', () => {
    // Вопрос уже задан, а ответ начался: «Удалить» в открытом окне стало бы
    // тем самым запрещённым действием.
    const onDelete = mock(async () => ({ ok: true }) as RemoveOutcome);
    const props = {
      conversations: [conversation(3)],
      activeId: 3,
      today: TODAY,
      hrefFor: (id: number) => `/chat?conversation=${id}`,
      onStart: () => {},
      onDelete,
    };
    const view = render(<ChatHistory {...props} />);
    fireEvent.click(deleteButton('Вопрос 3'));

    view.rerender(<ChatHistory {...props} deleteBlockedReason={() => 'Ответ ещё идёт.'} />);

    const confirmButton = within(confirmation('Вопрос 3')).getByRole('button', {
      name: 'Удалить',
    });
    expect(confirmButton.getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(confirmButton);
    expect(onDelete).not.toHaveBeenCalled();
  });

  it('locks every delete while a deletion started elsewhere is running', () => {
    render(<Harness onDelete={async () => ({ ok: true })} removing={3} />);

    expect(deleteButton('Вопрос 1').getAttribute('aria-disabled')).toBe('true');
  });

  it('has no delete at all when the screen gave it no handler', () => {
    renderHistory();

    expect(screen.queryAllByRole('button', { name: /Удалить разговор/ })).toHaveLength(0);
  });
});
