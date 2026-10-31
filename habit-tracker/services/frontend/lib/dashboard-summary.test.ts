// [review:need-review] #302
// summary: tests for the pure wording of the dashboard summary - dates without a time zone, minutes as hours, metric units, the sign and direction of a distance from the norm, day dots, workout bars and the Russian error text

import { describe, expect, it } from 'bun:test';
import { APIError } from '@/lib/api';
import {
  dashboardErrorMessage,
  deltaTone,
  formatDayShort,
  formatDelta,
  formatGeneratedAt,
  formatMetricValue,
  formatMinutes,
  formatRange,
  healthLabelText,
  streakDaysTally,
  workoutBarFractions,
} from './dashboard-summary';

describe('formatDayShort / formatRange', () => {
  it('names the day and the month without a time zone', () => {
    expect(formatDayShort('2026-10-28')).toBe('28 окт');
    expect(formatDayShort('2026-01-05')).toBe('5 янв');
  });

  it('gives the input back when it is not a date', () => {
    expect(formatDayShort('вчера')).toBe('вчера');
  });

  it('joins the window with a dash', () => {
    expect(formatRange('2026-10-25', '2026-10-31')).toBe('25 окт — 31 окт');
  });
});

describe('formatGeneratedAt', () => {
  it('reads the server wall clock out of the string and does not convert it', () => {
    expect(formatGeneratedAt('2026-10-31T09:00:00+01:00')).toBe('31 окт, 09:00');
    expect(formatGeneratedAt('2026-10-31T23:05:00Z')).toBe('31 окт, 23:05');
  });

  it('returns an empty string for text that is not a moment', () => {
    expect(formatGeneratedAt('soon')).toBe('');
  });
});

describe('formatMinutes', () => {
  it('uses hours from sixty minutes up', () => {
    expect(formatMinutes(432)).toBe('7 ч 12 мин');
    expect(formatMinutes(120)).toBe('2 ч');
    expect(formatMinutes(45)).toBe('45 мин');
    expect(formatMinutes(0)).toBe('0 мин');
  });
});

describe('formatMetricValue', () => {
  it('knows minutes, beats per minute and plain counts', () => {
    expect(formatMetricValue(432, 'min')).toBe('7 ч 12 мин');
    expect(formatMetricValue(58, 'count/min')).toBe('58 уд/мин');
    expect(formatMetricValue(14220, 'count')).toBe('14 220');
  });

  it('keeps an unknown unit as the server named it', () => {
    expect(formatMetricValue(61.5, 'ms')).toBe('61,5 мс');
    expect(formatMetricValue(3, 'zz')).toBe('3 zz');
  });

  it('is a dash when there is no value, never a zero', () => {
    expect(formatMetricValue(null, 'min')).toBe('—');
  });
});

describe('formatDelta', () => {
  it('writes the sign with a real minus', () => {
    expect(formatDelta(20, 'min')).toBe('+20 мин');
    expect(formatDelta(-2, 'count/min')).toBe('−2 уд/мин');
    expect(formatDelta(-75, 'min')).toBe('−1 ч 15 мин');
  });

  it('reads zero as on the norm', () => {
    expect(formatDelta(0, 'min')).toBe('на уровне нормы');
  });

  it('says the norm is not known yet when there is no distance', () => {
    expect(formatDelta(null, 'min')).toBe('нормы пока нет');
  });
});

describe('deltaTone', () => {
  it('counts more sleep as good and a lower resting pulse as good', () => {
    expect(deltaTone('sleep_duration', 20)).toBe('good');
    expect(deltaTone('sleep_duration', -20)).toBe('bad');
    expect(deltaTone('resting_heart_rate', -2)).toBe('good');
    expect(deltaTone('resting_heart_rate', 4)).toBe('bad');
  });

  it('reads the long catalog names the same way', () => {
    expect(deltaTone('HKQuantityTypeIdentifierRestingHeartRate', -3)).toBe('good');
    expect(deltaTone('HKCategoryTypeIdentifierSleepAnalysis', -30)).toBe('bad');
  });

  it('judges nothing it does not know and nothing at zero', () => {
    expect(deltaTone('steps', 100)).toBe('neutral');
    expect(deltaTone('sleep_duration', 0)).toBe('neutral');
    expect(deltaTone('sleep_duration', null)).toBe('neutral');
  });
});

describe('healthLabelText', () => {
  it('translates the labels the server knows and drops the rest', () => {
    expect(healthLabelText('good')).toBe('Хорошо');
    expect(healthLabelText('poor')).toBe('Ниже нормы');
    expect(healthLabelText('weird')).toBeNull();
    expect(healthLabelText(null)).toBeNull();
  });
});

describe('streakDaysTally', () => {
  it('counts the three states apart', () => {
    expect(streakDaysTally([true, true, false, null, true])).toEqual({
      done: 3,
      missed: 1,
      unknown: 1,
    });
  });
});

describe('workoutBarFractions', () => {
  it('scales to the busiest week and keeps an empty week at zero', () => {
    expect(
      workoutBarFractions([
        { week_start: '2026-10-05', count: 2, minutes: 90 },
        { week_start: '2026-10-12', count: 4, minutes: 200 },
        { week_start: '2026-10-19', count: 0, minutes: 0 },
      ])
    ).toEqual([0.5, 1, 0]);
  });

  it('does not divide by zero when no week has a workout', () => {
    expect(workoutBarFractions([{ week_start: '2026-10-05', count: 0, minutes: 0 }])).toEqual([0]);
  });
});

describe('dashboardErrorMessage', () => {
  it('speaks Russian and tells a server fault from a lost connection', () => {
    expect(dashboardErrorMessage(new APIError(500, 'An error occurred'))).toContain('Сервер');
    expect(dashboardErrorMessage(new TypeError('Failed to fetch'))).toContain('соединение');
    expect(dashboardErrorMessage(new APIError(500, 'x'))).not.toContain('Something went wrong');
  });
});
