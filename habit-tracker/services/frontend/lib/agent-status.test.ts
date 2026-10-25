// [review:need-review] PHASE-03/164
// summary: tests of the agent banners — silence is worded in minutes, hours and days, a silent agent gets the silence banner only (its other flags are old news), a live one gets one banner per cause, the switch is not worded as an error, and two macs are told apart

import { describe, expect, it } from 'bun:test';
import type { AgentStatus, AgentStatusItem } from '@/lib/api';
import {
  SILENT_BANNER_NOTE,
  TITLES_OFF_NOT_AN_ERROR,
  bannersFor,
  formatSilence,
} from './agent-status';

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

function status(...agents: AgentStatusItem[]): AgentStatus {
  return { agents, silence_threshold_seconds: 1800 };
}

describe('formatSilence', () => {
  it('words the time in the largest honest unit', () => {
    expect(formatSilence(45 * 60)).toBe('45 мин');
    expect(formatSilence(3 * HOUR)).toBe('3 ч');
    expect(formatSilence(3 * HOUR + 10 * 60)).toBe('3 ч 10 мин');
    expect(formatSilence(26 * HOUR)).toBe('1 дн 2 ч');
  });

  it('never says zero minutes', () => {
    expect(formatSilence(10)).toBe('1 мин');
  });
});

describe('bannersFor', () => {
  it('says nothing about a healthy agent', () => {
    expect(bannersFor(status(agent()))).toEqual([]);
  });

  it('says nothing when no agent has ever reported', () => {
    expect(bannersFor(status())).toEqual([]);
  });

  it('names the silence and says the intervals may be missing', () => {
    const [banner] = bannersFor(
      status(agent({ is_silent: true, silent_for_seconds: 3 * HOUR }))
    );

    expect(banner.kind).toBe('silent');
    expect(banner.title).toBe('Агент молчит 3 ч');
    expect(banner.body).toContain(SILENT_BANNER_NOTE);
    expect(banner.body).toContain('могут отсутствовать');
  });

  it('gives a missing Accessibility its own banner and no silence banner', () => {
    const banners = bannersFor(status(agent({ accessibility_granted: false })));

    expect(banners.map((b) => b.kind)).toEqual(['accessibility']);
  });

  it('gives the switched-off titles a separate banner that is not an error', () => {
    const [banner] = bannersFor(status(agent({ titles_enabled: false })));

    expect(banner.kind).toBe('titles_off');
    expect(banner.body).toContain(TITLES_OFF_NOT_AN_ERROR);
    expect(`${banner.title} ${banner.body}`).not.toMatch(/ошибк/i);
    expect(banner.action?.href).toBe('/agent/title-rules');
  });

  it('shows the cause banners next to each other when both hold', () => {
    const banners = bannersFor(
      status(agent({ accessibility_granted: false, titles_enabled: false }))
    );

    expect(banners.map((b) => b.kind)).toEqual(['accessibility', 'titles_off']);
  });

  it('keeps a silent agent to the silence banner: its flags are stale', () => {
    const banners = bannersFor(
      status(
        agent({
          is_silent: true,
          silent_for_seconds: HOUR,
          accessibility_granted: false,
          titles_enabled: false,
        })
      )
    );

    expect(banners.map((b) => b.kind)).toEqual(['silent']);
  });

  it('tells two macs apart and leaves one unlabelled', () => {
    const second = agent({
      agent_id: 'bbbbbbbb-0000-4000-8000-00000000a002',
      is_silent: true,
      silent_for_seconds: HOUR,
    });
    const both = bannersFor(status(agent({ titles_enabled: false }), second));
    const alone = bannersFor(status(second));

    expect(both.map((b) => b.agentLabel)).toEqual(['6f1b2c3d', 'bbbbbbbb']);
    expect(both.map((b) => b.key)).toEqual([
      '6f1b2c3d-0000-4000-8000-00000000a001:titles_off',
      'bbbbbbbb-0000-4000-8000-00000000a002:silent',
    ]);
    expect(alone[0].agentLabel).toBeNull();
  });
});
