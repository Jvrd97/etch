// [review:need-review] PHASE-03/120
// summary: tests for the live half of the feed — the thought shown while it happens and folded away by itself once the answer starts, the sign of life before the first word and the caret after it, the copy button on both sides of the conversation, and a long unbroken answer held inside a readable measure

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import ChatFeed from '@/components/chat/ChatFeed';
import { COPIED_LABEL, COPY_LABEL } from '@/components/chat/CopyButton';
import {
  THINKING_TOGGLE_TESTID,
  THINKING_WORDS_TESTID,
} from '@/components/chat/ThinkingBlock';
import { CARET_TESTID, WAITING_TESTID } from '@/components/chat/TurnLive';
import { NO_PROGRESS, THINKING_LABEL, type TurnProgress } from '@/lib/chat-progress';
import type { ChatTurn } from '@/hooks/useChat';
import type { ChatMessage } from '@/lib/api';

const QUESTION = 'как я спал на этой неделе?';
const THOUGHT = 'он спрашивает про сон — нужна выборка health_daily за 7 дней';
const ANSWER = 'В среднем 6 ч 40 мин.';

/** Ход, у которого модель уже начала думать. */
function thinking(overrides: Partial<TurnProgress> = {}): TurnProgress {
  return { activity: { kind: 'thinking' }, thinking: THOUGHT, thinkingTokens: null, ...overrides };
}

function streaming(text: string, progress: TurnProgress = thinking()): ChatTurn {
  return { phase: 'streaming', question: QUESTION, text, progress };
}

function feed(turn: ChatTurn, messages: ChatMessage[] = []) {
  return render(<ChatFeed messages={messages} turn={turn} emptyHint="пусто" />);
}

function message(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: 1,
    seq: 2,
    role: 'assistant',
    content: ANSWER,
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

describe('ChatFeed: ход мысли', () => {
  it('говорит, чем модель занята, пока она этим занята', () => {
    feed(streaming(''));

    expect(screen.getByTestId(THINKING_TOGGLE_TESTID).textContent).toContain(THINKING_LABEL);
  });

  it('держит мысль свёрнутой, пока её не раскрыли', () => {
    feed(streaming(''));

    expect(screen.queryByTestId(THINKING_WORDS_TESTID)).toBeNull();
    expect(screen.getByTestId(THINKING_TOGGLE_TESTID).getAttribute('aria-expanded')).toBe(
      'false'
    );
  });

  it('показывает слова мысли по нажатию', () => {
    feed(streaming(''));

    fireEvent.click(screen.getByTestId(THINKING_TOGGLE_TESTID));

    expect(screen.getByTestId(THINKING_WORDS_TESTID).textContent).toContain(THOUGHT);
  });

  it('сворачивает раскрытую мысль сам, когда пошёл ответ, и оставляет её доступной', () => {
    const view = feed(streaming(''));
    fireEvent.click(screen.getByTestId(THINKING_TOGGLE_TESTID));
    expect(screen.getByTestId(THINKING_WORDS_TESTID)).toBeTruthy();

    view.rerender(<ChatFeed messages={[]} turn={streaming(ANSWER)} emptyHint="пусто" />);

    expect(screen.queryByTestId(THINKING_WORDS_TESTID)).toBeNull();
    // «Свернулся» — не «исчез»: строку можно раскрыть обратно и после ответа.
    fireEvent.click(screen.getByTestId(THINKING_TOGGLE_TESTID));
    expect(screen.getByTestId(THINKING_WORDS_TESTID).textContent).toContain(THOUGHT);
  });

  it('не рисует блок у бэкенда, который шагов не называет', () => {
    // API-бэкенд не шлёт ни одного шага, и пустая строка «думает» там была бы
    // выдумкой экрана.
    feed(streaming('', NO_PROGRESS));

    expect(screen.queryByTestId(THINKING_TOGGLE_TESTID)).toBeNull();
  });

  it('не пускает мысль в текст ответа', () => {
    // Несущее: слова мысли — отдельное поле хода, и пузырь модели собирается
    // только из `text`.
    feed(streaming(ANSWER));

    const bubble = screen.getByText(ANSWER);
    expect(bubble.textContent).toBe(ANSWER);
  });
});

describe('ChatFeed: признак жизни', () => {
  it('показывает признак ожидания, пока не сказано ни слова', () => {
    feed(streaming(''));

    expect(screen.getByTestId(WAITING_TESTID)).toBeTruthy();
    expect(screen.queryByTestId(CARET_TESTID)).toBeNull();
  });

  it('меняет ожидание на курсор, когда текст пошёл', () => {
    feed(streaming(ANSWER));

    expect(screen.queryByTestId(WAITING_TESTID)).toBeNull();
    expect(screen.getByTestId(CARET_TESTID)).toBeTruthy();
  });

  it('убирает курсор у хода, который уже не идёт', () => {
    feed({
      phase: 'failed',
      question: QUESTION,
      text: ANSWER,
      progress: NO_PROGRESS,
      code: 'backend_failed',
    });

    expect(screen.queryByTestId(CARET_TESTID)).toBeNull();
    expect(screen.queryByTestId(WAITING_TESTID)).toBeNull();
  });

  it('называет ожидание словами для тех, кто его не видит', () => {
    feed(streaming(''));

    expect(screen.getByTestId(WAITING_TESTID).getAttribute('role')).toBe('status');
  });
});

describe('ChatFeed: копирование', () => {
  it('даёт скопировать и свою реплику, и ответ модели', async () => {
    const writeText = mock<(text: string) => Promise<void>>(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    });
    feed({ phase: 'idle' }, [
      message({ id: 1, role: 'user', content: QUESTION }),
      message({ id: 2, role: 'assistant', content: ANSWER }),
    ]);

    const buttons = screen.getAllByLabelText(COPY_LABEL);
    expect(buttons.length).toBe(2);

    fireEvent.click(buttons[1]);
    await screen.findByLabelText(COPIED_LABEL);
    expect(writeText.mock.calls[0][0]).toBe(ANSWER);
  });

  it('не предлагает копировать ход, который ещё ничего не сказал', () => {
    feed(streaming(''));

    // Своя реплика уже есть, ответа ещё нет: кнопка одна.
    expect(screen.getAllByLabelText(COPY_LABEL).length).toBe(1);
  });
});

describe('ChatFeed: длинный ответ', () => {
  /** Ссылка без пробелов — то, чем ломается строка, если ей это позволить. */
  const UNBROKEN = `https://example.org/${'a'.repeat(400)}`;

  it('переносит сплошную строку внутри пузыря, а не растягивает ряд', () => {
    feed({ phase: 'idle' }, [message({ status: 'interrupted', content: UNBROKEN })]);

    const bubble = screen.getByText(UNBROKEN).closest('.copy-host');
    expect(bubble).not.toBeNull();
    expect(bubble?.className).toContain('break-words');
  });

  it('держит ответ модели в читаемой ширине, а не в ширине контейнера', () => {
    // Прежние 90% от `max-w-7xl` давали строку под тысячу пикселей. Потолок
    // задан буквами: это и есть мера читаемости.
    feed({ phase: 'idle' }, [message({ status: 'interrupted', content: UNBROKEN })]);

    const bubble = screen.getByText(UNBROKEN).closest('.copy-host');
    expect(bubble?.className).toContain('ch,90%)]');
  });

  it('оставляет акцент своей реплике и не заливает им ответ', () => {
    feed({ phase: 'idle' }, [
      message({ id: 1, role: 'user', content: QUESTION }),
      message({ id: 2, role: 'assistant', content: ANSWER }),
    ]);

    const mine = screen.getByText(QUESTION).closest('.copy-host');
    const theirs = screen.getByText(ANSWER).closest('.copy-host');
    expect(mine?.className).toContain('bg-lime');
    expect(theirs?.className).not.toContain('bg-lime');
    expect(theirs?.className).toContain('bg-card');
  });
});
