// [review:need-review] PHASE-03/152
// summary: unit tests for the rules-screen logic — the draft refuses a start date that is not in the future before any request goes out, the percentage becomes the API's decimal ratio, and a version is placed against today as прожита / действует / выйдет

import { describe, expect, it } from 'bun:test';
import type { DayRuleSet } from '@/lib/api';
import {
  draftError,
  draftFromRule,
  draftToPayload,
  parseAnchors,
  parseWeekdays,
  ruleStanding,
  ruleStandingLabel,
} from './day-rules';

const RULE: DayRuleSet = {
  id: 2,
  valid_from: '2026-08-17',
  valid_to: null,
  timezone: 'Europe/Berlin',
  day_start_hour: 4,
  work_cap_min: 480,
  work_hard_cap_min: 540,
  work_stop_at: '16:00:00',
  max_work_tasks: 4,
  tasks_required_ratio: '1.00',
  overtime_disqualifies: true,
  overtime_lost_min: 600,
  max_study_items: 3,
  wake_at: '06:00:00',
  work_start: '09:00:00',
  review_at: '15:40:00',
  bedtime_max: '22:30:00',
  free_evening_start: '19:00:00',
  free_evening_end: '22:30:00',
  relationship_anchor_required: true,
  relationship_evening_start: '19:00:00',
  relationship_evening_end: '22:00:00',
  days_off: [6, 7],
  hard_edge_kinds: ['wake', 'sport', 'work_start', 'review', 'bedtime'],
  anchors: ['подъём', 'спорт', 'старт работы', 'ревью', 'отбой'],
  verdict_rule: {},
  workdays: [1, 2, 3, 4, 5],
  nocode_days: [2, 4],
  required_anchors: ['подъём', 'спорт', 'старт работы', 'ревью', 'отбой'],
  role_clause_enabled: true,
  role_clause_roles: 'cto,architect',
  note_md: 'действующий канон',
};

const EARLIEST = '2026-08-31';

function draft(overrides: Partial<ReturnType<typeof draftFromRule>> = {}) {
  return { ...draftFromRule(RULE, EARLIEST), ...overrides };
}

describe('draftFromRule', () => {
  it('prefills the form with the version in force', () => {
    const filled = draftFromRule(RULE, EARLIEST);
    expect(filled.workCapMin).toBe('480');
    expect(filled.workStopAt).toBe('16:00');
    expect(filled.workdays).toBe('1, 2, 3, 4, 5');
    expect(filled.requiredAnchors).toContain('подъём');
  });

  it('shows the task bar as a percentage, not as the API decimal', () => {
    expect(draftFromRule({ ...RULE, tasks_required_ratio: '0.80' }, EARLIEST)
      .tasksRequiredPercent).toBe('80');
  });
});

describe('draftError', () => {
  it('passes a draft that only changes the ceiling', () => {
    expect(draftError(draft({ workCapMin: '420', workHardCapMin: '420' }), EARLIEST)).toBeNull();
  });

  it('refuses a start date before the earliest the server allows', () => {
    const error = draftError(draft({ validFrom: '2026-08-30' }), EARLIEST);
    expect(error).toContain('2026-08-31');
    expect(error).toContain('не пересчитываются');
  });

  it('refuses an empty start date', () => {
    expect(draftError(draft({ validFrom: '' }), EARLIEST)).toContain('дата');
  });

  it('refuses an exception ceiling below the everyday one', () => {
    const error = draftError(draft({ workCapMin: '480', workHardCapMin: '420' }), EARLIEST);
    expect(error).toContain('исключение не бывает строже');
  });

  it('refuses a day-start hour outside the clock', () => {
    expect(draftError(draft({ dayStartHour: '24' }), EARLIEST)).toContain('Час начала суток');
  });

  it('refuses a ceiling that is not a whole number of minutes', () => {
    expect(draftError(draft({ workCapMin: '7,5' }), EARLIEST)).toContain('минут');
  });

  it('refuses a stop time that is not HH:MM', () => {
    expect(draftError(draft({ workStopAt: '16' }), EARLIEST)).toContain('ЧЧ:ММ');
  });

  it('refuses a task bar above 100 per cent', () => {
    expect(draftError(draft({ tasksRequiredPercent: '120' }), EARLIEST)).toContain('процент');
  });

  it('refuses a weekday that is not an ISO number', () => {
    expect(draftError(draft({ workdays: '1, 8' }), EARLIEST)).toContain('ISO');
  });

  it('refuses the same weekday twice', () => {
    expect(draftError(draft({ nocodeDays: '2, 2' }), EARLIEST)).toContain('повтор');
  });

  it('refuses the same anchor twice', () => {
    expect(draftError(draft({ requiredAnchors: 'подъём, подъём' }), EARLIEST)).toContain(
      'дважды'
    );
  });
});

describe('draftToPayload', () => {
  it('builds the payload the API takes', () => {
    const result = draftToPayload(
      draft({ workCapMin: '420', workHardCapMin: '420', noteMd: 'семь часов' }),
      EARLIEST
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.payload).toEqual({
      valid_from: '2026-08-31',
      timezone: 'Europe/Berlin',
      day_start_hour: 4,
      work_cap_min: 420,
      work_hard_cap_min: 420,
      work_stop_at: '16:00:00',
      max_work_tasks: 4,
      tasks_required_ratio: '1.00',
      overtime_disqualifies: true,
      workdays: [1, 2, 3, 4, 5],
      nocode_days: [2, 4],
      required_anchors: ['подъём', 'спорт', 'старт работы', 'ревью', 'отбой'],
      role_clause_enabled: true,
      role_clause_roles: 'cto,architect',
      note_md: 'семь часов',
    });
  });

  it('turns the percentage back into the decimal ratio', () => {
    const result = draftToPayload(draft({ tasksRequiredPercent: '80' }), EARLIEST);
    expect(result.ok && result.payload.tasks_required_ratio).toBe('0.80');
  });

  it('never builds a payload out of a draft that has not passed the checks', () => {
    const result = draftToPayload(draft({ validFrom: '2020-01-01' }), EARLIEST);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain('2026-08-31');
  });
});

describe('parseWeekdays', () => {
  it('reads a comma-separated list', () => {
    expect(parseWeekdays('1, 3,5')).toEqual([1, 3, 5]);
  });

  it('reads an empty list as no days at all', () => {
    expect(parseWeekdays('')).toEqual([]);
  });

  it('refuses a number outside the week', () => {
    expect(parseWeekdays('0')).toBeNull();
    expect(parseWeekdays('8')).toBeNull();
  });

  it('refuses a repeat', () => {
    expect(parseWeekdays('2,2')).toBeNull();
  });
});

describe('parseAnchors', () => {
  it('trims and drops the empties a trailing comma leaves', () => {
    expect(parseAnchors('подъём, спорт, ')).toEqual(['подъём', 'спорт']);
  });
});

describe('ruleStanding', () => {
  const today = '2026-08-30';

  it('calls a closed interval one that has already judged days', () => {
    expect(ruleStanding({ ...RULE, valid_from: '2020-01-01', valid_to: '2026-08-17' }, today)).toBe(
      'past'
    );
  });

  it('calls the open interval the one in force', () => {
    expect(ruleStanding(RULE, today)).toBe('current');
  });

  it('calls a version starting tomorrow a scheduled one', () => {
    expect(ruleStanding({ ...RULE, valid_from: '2026-08-31' }, today)).toBe('scheduled');
  });

  it('gives the day a version ends on to the next version', () => {
    // Half-open: `valid_to` is the first date the rule no longer applies, so a
    // version ending today is already past.
    expect(ruleStanding({ ...RULE, valid_to: today }, today)).toBe('past');
  });

  it('labels each standing in words', () => {
    expect(ruleStandingLabel('past')).toContain('прожит');
    expect(ruleStandingLabel('current')).toContain('действует');
    expect(ruleStandingLabel('scheduled')).toContain('вступит');
  });
});

describe('клауз роли в версии канона (#137)', () => {
  it('включённый клауз без единой роли не даёт опубликовать версию', () => {
    const result = draftToPayload(
      draft({ roleClauseEnabled: true, roleClauseRoles: '  ,  ' }),
      EARLIEST
    );

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain('Клауз роли');
  });

  it('выключенный клауз ролей не требует', () => {
    const result = draftToPayload(
      draft({ roleClauseEnabled: false, roleClauseRoles: '' }),
      EARLIEST
    );

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.payload.role_clause_enabled).toBe(false);
  });
});
