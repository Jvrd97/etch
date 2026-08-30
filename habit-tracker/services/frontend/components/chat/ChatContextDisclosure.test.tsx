// [review:need-review] PHASE-03/113
// summary: tests for the "что чат видит" disclosure — nothing is fetched until it is opened, the card is shown verbatim rather than summarised, the ceiling note names the sections that lost lines, and a second open does not refetch

import { afterEach, beforeEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ChatContext } from '@/lib/api';
import ChatContextDisclosure, {
  DISCLOSURE_LABEL,
} from '@/components/chat/ChatContextDisclosure';

const CARD_TEXT = [
  '# Карточка дня — 2026-08-31',
  '',
  '## Здоровье за день',
  'Шаги: 8421 count',
  '',
  '## Дневник',
  'Контрольная фраза дневника: якорь-113.',
].join('\n');

const CONTEXT: ChatContext = {
  conversation_id: 7,
  entry_date: '2026-08-31',
  text: CARD_TEXT,
  chars: CARD_TEXT.length,
  max_chars: 20000,
  truncated: false,
  dropped_sections: [],
};

let answer: ChatContext;
let calls: number;

// Чтение подставляется пропсом, а не подменой модуля `@/lib/api`: подмена
// в bun действует на весь процесс, и соседние наборы тестов теряли бы из него
// то, чем пользуются сами.
async function load(): Promise<ChatContext> {
  calls += 1;
  return answer;
}

beforeEach(() => {
  answer = CONTEXT;
  calls = 0;
});

afterEach(() => {
  cleanup();
});

function open(): HTMLElement {
  const button = screen.getByRole('button', { name: DISCLOSURE_LABEL });
  fireEvent.click(button);
  return button;
}

describe('раскрывашка «что чат видит»', () => {
  it('ничего не читает, пока её не раскрыли', () => {
    render(<ChatContextDisclosure conversationId={7} load={load} />);

    expect(calls).toBe(0);
    expect(screen.queryByTestId('context-size')).toBeNull();
  });

  it('показывает карточку тем же текстом, а не пересказом', async () => {
    render(<ChatContextDisclosure conversationId={7} load={load} />);

    open();

    await waitFor(() => expect(screen.getByTestId('context-size')).toBeTruthy());
    // Фразу из карточки можно найти на экране целиком — ради этого раскрывашка
    // и существует.
    expect(screen.getByTestId('context-card').textContent).toBe(CARD_TEXT);
    expect(screen.getByTestId('context-size').textContent).toBe(
      `${CARD_TEXT.length} из 20 000 знаков`
    );
    expect(screen.queryByTestId('context-note')).toBeNull();
  });

  it('называет секции, у которых потолок съел строки', async () => {
    answer = {
      ...CONTEXT,
      truncated: true,
      dropped_sections: ['journal', 'entries'],
    };
    render(<ChatContextDisclosure conversationId={7} load={load} />);

    open();

    await waitFor(() => expect(screen.getByTestId('context-note')).toBeTruthy());
    expect(screen.getByTestId('context-note').textContent).toBe(
      'Обрезано по потолку, строки потеряли: дневник, записи трекера.'
    );
  });

  it('не перечитывает карточку на повторном раскрытии', async () => {
    render(<ChatContextDisclosure conversationId={7} load={load} />);

    const button = open();
    await waitFor(() => expect(screen.getByTestId('context-size')).toBeTruthy());
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByTestId('context-size')).toBeTruthy());
    expect(calls).toBe(1);
  });
});
