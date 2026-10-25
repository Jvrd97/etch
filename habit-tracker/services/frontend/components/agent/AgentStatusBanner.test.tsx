// [review:need-review] PHASE-03/164
// summary: component tests of the agent banner on the day screen — three distinct states with their own words, none for a healthy agent, none on a day that is not today, and the silence banner telling the intervals may be missing

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { AgentStatus, AgentStatusItem } from '@/lib/api';
import AgentStatusBanner from './AgentStatusBanner';

afterEach(() => {
  cleanup();
});

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

function show(item: AgentStatusItem | null, date = TODAY) {
  const status: AgentStatus | null =
    item === null ? null : { agents: [item], silence_threshold_seconds: 1800 };
  return render(<AgentStatusBanner status={status} date={date} today={TODAY} />);
}

describe('AgentStatusBanner', () => {
  it('draws nothing before the status is known or for a healthy agent', () => {
    const { container, rerender } = show(null);
    expect(container.textContent).toBe('');

    rerender(
      <AgentStatusBanner
        status={{ agents: [agent()], silence_threshold_seconds: 1800 }}
        date={TODAY}
        today={TODAY}
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

  it('stays quiet on a day that is not today: silence now says nothing about it', () => {
    const { container } = show(
      agent({ is_silent: true, silent_for_seconds: 3 * HOUR }),
      '2026-10-20'
    );

    expect(container.textContent).toBe('');
  });
});
