// [review:need-review] PHASE-03/147, PHASE-03/148, PHASE-03/164, PHASE-03/220, #311
// summary: #311 round 3 — a failed re-read keeps the day on screen with the message above it, and an unconfirmed «today» locks the day's controls with a status line
// summary: PHASE-03/220 — the Claude Code block stands on this shell, is asked for the day of the screen (the server's, not the browser's) and says nothing when it has no answer
// summary: PHASE-03/164 — the agent banner stands on today's screen when the agent is silent and is absent on any other day
// summary: tests for the mobile day screen — the day with no plan carries the same button out of it as the desktop shell does, the button is gone the moment there is a plan, and a plan the skeleton assembled says so and says why

import { afterEach, beforeEach, describe, expect, it, mock, setSystemTime } from 'bun:test';
import { cleanup, render, screen, within } from '@testing-library/react';
import type { AgentStatus, ClaudeUsageDay, DayDetail, PlanViolation } from '@/lib/api';
import { DAY, PLAN } from '@/test-fixtures/day';
import { DAY_CHECKING, DAY_LOCKED } from '@/components/day/DayWriteNotice';
import { BUILD_PLAN_LABEL } from '@/components/day/PlanBuilder';
import { FALLBACK_REASON_LABELS, planAuthorLabel } from '@/lib/plan-violations';

let state: {
  detail: DayDetail | null;
  loading: boolean;
  error: string | null;
  violations: PlanViolation[];
  reload: () => void;
  writeDate: string;
};

// The hook rather than the API client: the shell's contract is the hook, and
// both shells are held to the same one.
mock.module('@/hooks/useDay', () => ({
  useDay: () => state,
}));

// The agent banner reads its own hook; a status of null draws nothing, so the
// other suites that render this screen are not touched by it.
let agent: AgentStatus | null = null;
mock.module('@/hooks/useAgentStatus', () => ({
  useAgentStatus: () => agent,
}));

// The Claude Code block reads its own hook; the date it is asked for is recorded,
// because the day must come from the screen's detail and not from the browser clock.
let claude: ClaudeUsageDay | null = null;
const claudeAsked: Array<string | null> = [];
mock.module('@/hooks/useClaudeUsage', () => ({
  useClaudeUsage: (date: string | null) => {
    claudeAsked.push(date);
    return claude;
  },
}));

const { default: MobileDayScreen } = await import('./MobileDayScreen');

beforeEach(() => {
  agent = null;
  claude = null;
  claudeAsked.length = 0;
  state = { detail: DAY, loading: false, error: null, violations: [], reload: () => {}, writeDate: DAY.day.date };
});

afterEach(() => {
  cleanup();
});

describe('MobileDayScreen и день без плана', () => {
  it('даёт тот же выход, что большой экран', () => {
    // Один компонент на оба шелла: телефон — это тот же день, а не его
    // урезанная версия, и собирать план с него можно ровно так же.
    render(<MobileDayScreen date="2026-08-30" />);

    expect(screen.getByText(BUILD_PLAN_LABEL)).toBeDefined();
  });

  it('убирает кнопку, как только план есть', () => {
    state = { ...state, detail: { ...DAY, plan: PLAN, has_plan: true } };
    render(<MobileDayScreen date="2026-08-30" />);

    expect(screen.queryByText(BUILD_PLAN_LABEL)).toBeNull();
    expect(screen.getByText('Воскресный блок')).toBeDefined();
  });

  it('называет скелет скелетом и говорит, почему не модель', () => {
    const skeleton = {
      ...PLAN,
      source: 'fallback' as const,
      fallback_reason: 'llm_timeout' as const,
    };
    state = { ...state, detail: { ...DAY, plan: skeleton, has_plan: true } };
    render(<MobileDayScreen date="2026-08-30" />);

    expect(screen.getByText(planAuthorLabel(skeleton))).toBeDefined();
    expect(
      screen.getByText(`Почему: ${FALLBACK_REASON_LABELS.llm_timeout}`)
    ).toBeDefined();
  });
});

// The server's today. It is not the calendar date of the machine running the test,
// so a banner that compared against the browser's date would not show.
const SERVER_TODAY = '2026-10-26';

const SILENT_THREE_HOURS: AgentStatus = {
  silence_threshold_seconds: 1800,
  today: SERVER_TODAY,
  agents: [
    {
      agent_id: '6f1b2c3d-0000-4000-8000-00000000a001',
      agent_version: '0.3.0',
      reported_at: '2026-10-25T09:00:00Z',
      accessibility_granted: true,
      titles_enabled: true,
      sampling_seconds: 5,
      queue_depth: 0,
      last_flush_at: null,
      last_error: null,
      silent_for_seconds: 3 * 3600,
      is_silent: true,
    },
  ],
};

describe('MobileDayScreen and the agent banner', () => {
  it('says the agent is silent on the screen of today', () => {
    agent = SILENT_THREE_HOURS;
    state = { ...state, detail: { ...DAY, day: { ...DAY.day, date: SERVER_TODAY } } };
    render(<MobileDayScreen date={SERVER_TODAY} />);

    expect(screen.getByText('Агент молчит 3 ч')).toBeDefined();
  });

  it('keeps the banner at 01:00 local, when the browser calendar is a day ahead of the server', () => {
    agent = SILENT_THREE_HOURS;
    state = { ...state, detail: { ...DAY, day: { ...DAY.day, date: SERVER_TODAY } } };
    // 01:00 on 2026-10-27 in the browser; the server is still in 2026-10-26.
    setSystemTime(new Date(2026, 9, 27, 1, 0, 0));
    try {
      render(<MobileDayScreen date={null} />);
      expect(screen.getByText('Агент молчит 3 ч')).toBeDefined();
    } finally {
      setSystemTime();
    }
  });

  it('stays out of the way on any other day', () => {
    agent = SILENT_THREE_HOURS;
    render(<MobileDayScreen date="2026-08-30" />);

    expect(screen.queryByText(/Агент молчит/)).toBeNull();
  });
});

const CLAUDE_TODAY: ClaudeUsageDay = {
  date: SERVER_TODAY,
  today: SERVER_TODAY,
  sessions: 3,
  assistant_turns: 42,
  input_tokens: 12_400,
  output_tokens: 3_100,
  cache_read_tokens: 1_250_000,
  cache_creation_tokens: 80_000,
  sessions_past_boundary: 1,
};

describe('MobileDayScreen and the Claude Code block', () => {
  it('shows the sessions, turns and tokens of the day', () => {
    claude = CLAUDE_TODAY;
    state = { ...state, detail: { ...DAY, day: { ...DAY.day, date: SERVER_TODAY } } };
    render(<MobileDayScreen date={SERVER_TODAY} />);

    const block = screen.getByRole('region', { name: 'Claude Code' });
    expect(block.textContent).toContain('42');
    expect(block.textContent).toContain('12,4 тыс вход');
    expect(block.textContent).toContain('целиком на день начала');
  });

  it('asks for the day the server named, at 01:00 local when the browser is a day ahead', () => {
    claude = CLAUDE_TODAY;
    state = { ...state, detail: { ...DAY, day: { ...DAY.day, date: SERVER_TODAY } } };
    setSystemTime(new Date(2026, 9, 27, 1, 0, 0));
    try {
      render(<MobileDayScreen date={null} />);
      expect(claudeAsked).toContain(SERVER_TODAY);
      expect(claudeAsked).not.toContain('2026-10-27');
    } finally {
      setSystemTime();
    }
  });

  it('draws no block before the answer', () => {
    render(<MobileDayScreen date={SERVER_TODAY} />);

    expect(screen.queryByRole('region', { name: 'Claude Code' })).toBeNull();
  });
});

describe('MobileDayScreen: a day on screen that cannot be re-read or written into', () => {
  it('keeps the day and says the re-read failed', () => {
    state = { ...state, error: 'offline' };
    render(<MobileDayScreen date={DAY.day.date} />);

    expect(screen.getAllByText(DAY.day.date).length).toBeGreaterThan(0);
    expect(within(screen.getByRole('alert')).getByText('offline')).toBeDefined();
  });

  it('locks the controls while the cached today waits for the server', () => {
    state = { ...state, writeDate: '' };
    const { container } = render(<MobileDayScreen date={null} />);

    const reason = screen.getByText(DAY_CHECKING);
    const locked = container.querySelector('fieldset');
    expect(locked?.hasAttribute('disabled')).toBe(true);
    expect(locked?.getAttribute('aria-describedby')).toBe(reason.id);
  });

  it('says why the controls stay locked when the re-read failed', () => {
    state = { ...state, writeDate: '', error: 'offline' };
    render(<MobileDayScreen date={null} />);

    expect(screen.getByText(DAY_LOCKED)).toBeDefined();
    expect(screen.getAllByText(DAY.day.date).length).toBeGreaterThan(0);
  });

  it('leaves the controls open on a confirmed day', () => {
    const { container } = render(<MobileDayScreen date={null} />);

    expect(container.querySelector('fieldset')?.hasAttribute('disabled')).toBe(false);
    expect(screen.queryByText(DAY_CHECKING)).toBeNull();
  });
});
