// [review:need-review] PHASE-03/220
// summary: component tests of the Claude Code block — sessions, assistant turns and tokens as counters, nothing before the first answer, a quiet zero on the server's today and no block on an empty past day, the boundary caption, and a labelled region for assistive technology

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen, within } from '@testing-library/react';
import type { ClaudeUsageDay } from '@/lib/api';
import ClaudeUsageBlock from './ClaudeUsageBlock';

afterEach(() => {
  cleanup();
});

const TODAY = '2026-10-26';

function usage(overrides: Partial<ClaudeUsageDay> = {}): ClaudeUsageDay {
  return {
    date: TODAY,
    today: TODAY,
    sessions: 3,
    assistant_turns: 42,
    input_tokens: 12_400,
    output_tokens: 3_100,
    cache_read_tokens: 1_250_000,
    cache_creation_tokens: 80_000,
    sessions_past_boundary: 0,
    ...overrides,
  };
}

describe('ClaudeUsageBlock', () => {
  it('draws nothing before the first answer', () => {
    const { container } = render(<ClaudeUsageBlock usage={null} />);

    expect(container.textContent).toBe('');
  });

  it('shows sessions, assistant turns and tokens as counters', () => {
    render(<ClaudeUsageBlock usage={usage()} />);

    const region = screen.getByRole('region', { name: 'Claude Code' });
    const stats = within(region);
    expect(stats.getByText('Сессии').nextElementSibling?.textContent).toBe('3');
    expect(stats.getByText('Ходы ассистента').nextElementSibling?.textContent).toBe('42');
    expect(stats.getByText('Токены').nextElementSibling?.textContent).toBe('12,4 тыс вход · 3,1 тыс выход');
    expect(stats.getByText('Кеш').nextElementSibling?.textContent).toBe('1,3 млн чтение · 80 тыс запись');
  });

  it('says the session counts whole on its start day, and how many ran past the boundary', () => {
    const { rerender } = render(<ClaudeUsageBlock usage={usage()} />);
    expect(screen.getByText(/целиком на день начала/)).toBeTruthy();
    expect(screen.queryByText(/продолжившихся/)).toBeNull();

    rerender(<ClaudeUsageBlock usage={usage({ sessions_past_boundary: 2 })} />);
    expect(screen.getByText(/продолжившихся после границы суток: 2/)).toBeTruthy();
  });

  it('says there were no sessions on the server today instead of vanishing', () => {
    render(
      <ClaudeUsageBlock
        usage={usage({ sessions: 0, assistant_turns: 0, input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0 })}
      />
    );

    expect(screen.getByText('Сегодня сессий Claude Code не было')).toBeTruthy();
    expect(screen.queryByText('Токены')).toBeNull();
  });

  it('draws nothing for a past day that had no sessions', () => {
    const { container } = render(
      <ClaudeUsageBlock usage={usage({ date: '2026-10-20', sessions: 0, assistant_turns: 0 })} />
    );

    expect(container.textContent).toBe('');
  });

  it('shows a past day with sessions, without the word today', () => {
    render(<ClaudeUsageBlock usage={usage({ date: '2026-10-20' })} />);

    expect(screen.getByRole('region', { name: 'Claude Code' })).toBeTruthy();
    expect(screen.queryByText(/Сегодня/)).toBeNull();
  });
});
