// [review:need-review] PHASE-03/86, PHASE-03/90, PHASE-03/143
// summary: tests for the day labels — weekday names in week order, minutes read as hours, the ratio as a percentage, the rule's validity interval spelled out, and the verdict of a day with the condition it failed on the streak in countable Russian, and the heading a day gets by the stage of its closing

import { describe, expect, it } from 'bun:test';
import type { Day, DayRuleSet } from '@/lib/api';
import {
  dayKindLabel,
  formatClock,
  formatMinutes,
  formatRatio,
  missingDataLabel,
  ruleLines,
  ruleValidity,
  streakLabel,
  closingHeadline,
  VERDICT_LATER,
  verdictLabel,
  verdictOriginLabel,
  verdictReasonLabel,
  weekdayNames,
} from './day-format';

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
  workdays: [1, 2, 3, 4, 5],
  nocode_days: [2, 4],
  required_anchors: ['подъём'],
  overtime_lost_min: 600,
  max_study_items: 2,
  wake_at: '06:00:00',
  work_start: '07:45:00',
  review_at: '15:40:00',
  bedtime_max: '22:30:00',
  free_evening_start: '19:10:00',
  free_evening_end: '21:00:00',
  relationship_anchor_required: true,
  relationship_evening_start: '18:30:00',
  relationship_evening_end: '21:00:00',
  days_off: [6, 7],
  hard_edge_kinds: ['anchor', 'hard_point'],
  anchors: ['подъём', 'relationship'],
  verdict_rule: { reason_order: ['overtime', 'anchors', 'tasks'] },
  role_clause_enabled: true,
  role_clause_roles: 'cto,architect',
  note_md: 'канон',
};

const WORKDAY: Day = {
  date: '2026-08-28',
  kind: 'work',
  is_nocode: false,
  opened_at: null,
  last_touched_at: null,
};

describe('dayKindLabel', () => {
  it('names a working day and a day off', () => {
    expect(dayKindLabel(WORKDAY)).toBe('рабочий день');
    expect(dayKindLabel({ ...WORKDAY, kind: 'off' })).toBe('выходной');
  });
});

describe('weekdayNames', () => {
  it('reads ISO numbers with Monday as 1', () => {
    expect(weekdayNames([1, 7])).toEqual(['пн', 'вс']);
  });

  it('keeps week order regardless of the order given', () => {
    expect(weekdayNames([4, 2])).toEqual(['вт', 'чт']);
  });

  it('has nothing to say about an empty schedule', () => {
    expect(weekdayNames([])).toEqual([]);
  });
});

describe('formatMinutes', () => {
  it('reads a whole number of hours as hours', () => {
    expect(formatMinutes(480)).toBe('8 ч');
  });

  it('keeps the remaining minutes', () => {
    expect(formatMinutes(545)).toBe('9 ч 5 мин');
  });

  it('falls back to minutes below the hour', () => {
    expect(formatMinutes(45)).toBe('45 мин');
  });

  it('shows a window across midnight as the hour the server measured', () => {
    // Смысл того, что минуты приезжают с сервера: здесь никто не знает, что
    // день идёт с 04:00 до 04:00, и знать не обязан.
    expect(formatMinutes(60)).toBe('1 ч');
  });
});

describe('formatClock', () => {
  it('drops the seconds the API sends', () => {
    expect(formatClock('16:00:00')).toBe('16:00');
  });
});

describe('formatRatio', () => {
  it('reads the decimal string as a percentage', () => {
    expect(formatRatio('1.00')).toBe('100%');
    expect(formatRatio('0.80')).toBe('80%');
  });

  it('shows an unparsable value as it came rather than as NaN', () => {
    expect(formatRatio('—')).toBe('—');
  });
});

describe('ruleLines', () => {
  it('spells the ceiling, the stop and the overtime rule', () => {
    const lines = ruleLines(RULE);
    const byLabel = new Map(lines.map((line) => [line.label, line.value]));

    expect(byLabel.get('Работа')).toBe('8 ч в день');
    expect(byLabel.get('Стоп')).toBe('16:00');
    expect(byLabel.get('Переработка')).toBe('день не выигран');
    expect(byLabel.get('Закрыть задач')).toBe('100%');
  });

  it('says the boundary hour, since it is what makes 00:30 yesterday', () => {
    const byLabel = new Map(ruleLines(RULE).map((line) => [line.label, line.value]));
    expect(byLabel.get('Сутки')).toBe('Europe/Berlin, с 04:00');
  });

  it('says "нет" instead of an empty line when nothing is a no-code day', () => {
    const byLabel = new Map(
      ruleLines({ ...RULE, nocode_days: [] }).map((line) => [line.label, line.value])
    );
    expect(byLabel.get('No-code дни')).toBe('нет');
  });
});

describe('ruleValidity', () => {
  it('reads an open interval as still in force', () => {
    expect(ruleValidity(RULE)).toBe('действует с 2026-08-17');
  });

  it('reads a closed interval in the past tense', () => {
    expect(ruleValidity({ ...RULE, valid_to: '2026-08-17' })).toBe(
      'действовало с 2026-08-17 по 2026-08-17'
    );
  });
});

describe('the verdict of a day', () => {
  it('names the condition that was not met, not "день не выигран"', () => {
    // The whole complaint of `#90`: a reader told only that the day was lost
    // has to guess which of three things to fix.
    expect(verdictReasonLabel('tasks')).toBe('задачи');
    expect(verdictReasonLabel('anchors')).toBe('якоря');
    expect(verdictReasonLabel('overtime')).toBe('переработка');
    expect(verdictReasonLabel('not_closed')).toBe('день не закрыт');
  });

  it('says nothing where every condition was met', () => {
    expect(verdictReasonLabel('')).toBe('');
  });

  it('reads a verdict, and reads its absence as "не закрыт"', () => {
    expect(verdictLabel('won')).toBe('День выигран');
    expect(verdictLabel('lost')).toBe('День проигран');
    expect(verdictLabel(null)).toBe('День не закрыт');
  });

  it('tells a verdict computed here from one carried over from a record', () => {
    // Перенесённый вердикт пересчитать нечем, и человек, читающий август,
    // обязан видеть это на экране, а не узнавать при попытке перезакрыть день.
    expect(verdictOriginLabel('computed')).toBe('вычислен');
    expect(verdictOriginLabel('migrated_prose')).toBe('из записи');
    expect(verdictOriginLabel('none')).toBe('');
  });

  it('says what could not be judged in Russian, not in codes', () => {
    expect(missingDataLabel('work_minutes')).toBe('время не измерено');
  });

  it('counts the streak the way Russian counts', () => {
    expect(streakLabel(0)).toBe('0 дней');
    expect(streakLabel(1)).toBe('1 день');
    expect(streakLabel(2)).toBe('2 дня');
    expect(streakLabel(5)).toBe('5 дней');
    expect(streakLabel(11)).toBe('11 дней');
    expect(streakLabel(21)).toBe('21 день');
    expect(streakLabel(22)).toBe('22 дня');
    expect(streakLabel(112)).toBe('112 дней');
  });

  it('splits "не закрыл" by the stage of closing', () => {
    // Пустой вердикт значит разное на разных стадиях, и прочесть «рано» как
    // «день не закрыт» — потеря, ради которой стадия и заведена.
    expect(closingHeadline('open', null)).toBe('День не закрыт');
    expect(closingHeadline('reviewed', null)).toBe(VERDICT_LATER);
    expect(closingHeadline('closed', 'won')).toBe('День выигран');
    expect(closingHeadline('closed', 'lost')).toBe('День проигран');
  });
});
