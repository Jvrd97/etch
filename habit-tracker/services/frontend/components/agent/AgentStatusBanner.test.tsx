// [review:need-review] PHASE-03/164, PHASE-03/220
// summary: PHASE-03/220 — the Claude Code log format error is on the banner in words, with no code, on the server's today
// summary: component tests of the agent banner on the day screen — three distinct states with their own words, none for a healthy agent, none on a day that is not the server's today (also at 01:00 local, when the browser's date is already tomorrow), and the silence banner telling the intervals may be missing

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { AgentStatus, AgentStatusItem } from '@/lib/api';
import AgentStatusBanner from './AgentStatusBanner';

afterEach(() => {
  cleanup();
});

// The server's today, deliberately not the calendar date of the machine running the test.
const TODAY = '2026-10-25';
const HOUR = 3600;

function agent(overrides: Partial<AgentStatusItem> = {}): AgentStatusItem {
  return {
    agent_id: '6f1b2c3d-0000-4000-8000-00000000a001',
    agent_version: '0.3.0',
    reported_at: '2026-10-25T12:00:00Z',
    accessibility_granted: true,
    titles_enabled: true,
    sampling_seconds: 5,
    queue_depth: 0,
    last_flush_at: null,
    last_error: null,
    silent_for_seconds: 60,
    is_silent: false,
    ...overrides,
  };
}

function show(item: AgentStatusItem | null, date = TODAY, today = TODAY) {
  const status: AgentStatus | null =
    item === null ? null : { agents: [item], silence_threshold_seconds: 1800, today };
  return render(<AgentStatusBanner status={status} date={date} />);
}

describe('AgentStatusBanner', () => {
  it('draws nothing before the status is known or for a healthy agent', () => {
    const { container, rerender } = show(null);
    expect(container.textContent).toBe('');

    rerender(
      <AgentStatusBanner
        status={{ agents: [agent()], silence_threshold_seconds: 1800, today: TODAY }}
        date={TODAY}
      />
    );
    expect(container.textContent).toBe('');
  });

  it('says the agent has been silent for three hours and the intervals may be missing', () => {
    show(agent({ is_silent: true, silent_for_seconds: 3 * HOUR }));

    expect(screen.getByText('Агент молчит 3 ч')).toBeTruthy();
    expect(screen.getByText(/могут отсутствовать/)).toBeTruthy();
    expect(screen.queryByText(/Accessibility/)).toBeNull();
  });

  it('an unknown Accessibility (null) draws no banner, a refused one does, a granted one does not', () => {
    const { container, rerender } = show(agent({ accessibility_granted: null }));
    expect(container.textContent).toBe('');

    rerender(
      <AgentStatusBanner
        status={{
          agents: [agent({ accessibility_granted: false })],
          silence_threshold_seconds: 1800,
          today: TODAY,
        }}
        date={TODAY}
      />
    );
    expect(screen.getByText(/нет доступа Accessibility/)).toBeTruthy();

    rerender(
      <AgentStatusBanner
        status={{
          agents: [agent({ accessibility_granted: true })],
          silence_threshold_seconds: 1800,
          today: TODAY,
        }}
        date={TODAY}
      />
    );
    expect(container.textContent).toBe('');
  });

  it('a silent agent is still called silent when its flags are unknown', () => {
    show(agent({ is_silent: true, silent_for_seconds: 3 * HOUR, accessibility_granted: null }));
    expect(screen.getByText('Агент молчит 3 ч')).toBeTruthy();
  });

  it('a missing Accessibility is its own banner and the agent is not called silent', () => {
    show(agent({ accessibility_granted: false }));

    expect(screen.getByText(/нет доступа Accessibility/)).toBeTruthy();
    expect(screen.queryByText(/Агент молчит/)).toBeNull();
  });

  it('the titles switch is a third banner worded as a setting, with the link to the rules', () => {
    show(agent({ titles_enabled: false }));

    expect(screen.getByText('Заголовки окон выключены')).toBeTruthy();
    expect(screen.getByText(/настройка, а не сбой/)).toBeTruthy();
    const link = screen.getByRole('link');
    expect(link.getAttribute('href')).toBe('/agent/title-rules');
    expect(screen.queryByText(/Агент молчит/)).toBeNull();
  });

  it('says in words that the Claude Code logs are not recognised', () => {
    const { container } = show(agent({ last_error: 'claude_format' }));

    expect(screen.getByText('Агент не читает журналы Claude Code')).toBeTruthy();
    expect(screen.getByText(/формат мог измениться/)).toBeTruthy();
    expect(container.textContent).not.toContain('claude_format');
    expect(container.querySelector('[data-banner="claude_format"]')?.getAttribute('role')).toBe('status');
  });

  it('stays quiet on a day that is not today: silence now says nothing about it', () => {
    const { container } = show(
      agent({ is_silent: true, silent_for_seconds: 3 * HOUR }),
      '2026-10-20'
    );

    expect(container.textContent).toBe('');
  });

  it('shows on the server day after midnight, when the browser calendar is a day ahead', () => {
    // 01:00 local: the server is still in 2026-10-25 (its day starts at 04:00),
    // the browser's calendar already says 2026-10-26. The day on screen is the
    // server's, so the banner stays.
    show(agent({ is_silent: true, silent_for_seconds: 3 * HOUR }), TODAY, TODAY);
    expect(screen.getByText('Агент молчит 3 ч')).toBeTruthy();
  });

  it('follows the server when it has moved on: the old day loses the banner', () => {
    const { container } = show(
      agent({ is_silent: true, silent_for_seconds: 3 * HOUR }),
      TODAY,
      '2026-10-26'
    );

    expect(container.textContent).toBe('');
  });
});
