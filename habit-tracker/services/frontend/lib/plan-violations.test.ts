// [review:need-review] PHASE-03/147
// summary: tests for the pure reading of a day's violations — lines found by id and never by text, the rules that name no line kept rather than lost, the rule spelled in Russian, and who assembled the plan

import { describe, expect, it } from 'bun:test';
import type { PlanViolation } from '@/lib/api';
import {
  FALLBACK_REASON_LABELS,
  planAuthorLabel,
  planFallbackLabel,
  planWideViolations,
  ruleLabel,
  violationsByItem,
} from './plan-violations';

function violation(overrides: Partial<PlanViolation> = {}): PlanViolation {
  return {
    id: 1,
    day_date: '2026-09-02',
    rule_code: 'free_evening_empty',
    severity: 'warn',
    origin: 'human',
    detail: {},
    created_at: '2026-09-02T10:00:00Z',
    ...overrides,
  };
}

describe('violationsByItem', () => {
  it('finds the lines a rule was recorded on, by id', () => {
    const found = violationsByItem([
      violation({ id: 1, detail: { item_ids: ['a', 'b'] } }),
      violation({ id: 2, rule_code: 'no_overlap', detail: { item_ids: ['b'] } }),
    ]);

    expect(found.get('a')?.map((v) => v.id)).toEqual([1]);
    expect(found.get('b')?.map((v) => v.id)).toEqual([1, 2]);
  });

  it('ignores a violation that names no line', () => {
    const found = violationsByItem([violation({ detail: { missing_codes: ['спорт'] } })]);

    expect(found.size).toBe(0);
  });

  it('survives a detail whose ids are not strings', () => {
    // The column is jsonb and the row outlives the code that wrote it; a shape
    // nobody expected must not take the day screen down with it.
    const found = violationsByItem([violation({ detail: { item_ids: [7, null] } })]);

    expect(found.size).toBe(0);
  });
});

describe('planWideViolations', () => {
  it('keeps the ones whose offending line is the one that is missing', () => {
    const missing = violation({
      id: 5,
      rule_code: 'health_before_work',
      detail: { missing_codes: ['спорт'] },
    });

    const wide = planWideViolations([
      missing,
      violation({ id: 6, detail: { item_ids: ['a'] } }),
    ]);

    expect(wide.map((v) => v.id)).toEqual([5]);
  });
});

describe('ruleLabel', () => {
  it('says what to fix rather than naming a code', () => {
    expect(ruleLabel('free_evening_empty')).toBe('свободный вечер не расписывается');
  });

  it('falls back to the code for a rule this build has not heard of', () => {
    expect(ruleLabel('a_ninth_rule')).toBe('a_ninth_rule');
  });
});

describe('planAuthorLabel', () => {
  it('reads the column rather than the title, which a person rewrites', () => {
    expect(planAuthorLabel({ source: 'manual' })).toBe('Собран скелетом из канона');
    expect(planAuthorLabel({ source: 'import' })).toBe('Перенесён из файлов');
    expect(planAuthorLabel({ source: 'day-open' })).toBe('Собран на /day-open');
  });

  it('tells a plan the model wrote from one the skeleton wrote', () => {
    expect(planAuthorLabel({ source: 'llm' })).toBe('Собран моделью и проверен каноном');
    expect(planAuthorLabel({ source: 'fallback' })).toBe('Собран скелетом из канона');
  });
});

describe('planFallbackLabel', () => {
  it('names the reason the model did not write the day', () => {
    expect(
      planFallbackLabel({ source: 'fallback', fallback_reason: 'llm_timeout' })
    ).toBe(`Почему: ${FALLBACK_REASON_LABELS.llm_timeout}`);
  });

  it('answers four different reasons, not one «не получилось»', () => {
    const said = new Set(Object.values(FALLBACK_REASON_LABELS));
    expect(said.size).toBe(4);
  });

  it('says nothing about a plan the skeleton did not write', () => {
    expect(planFallbackLabel({ source: 'llm', fallback_reason: null })).toBeNull();
    expect(
      // Причина без запасного авторства — это рассинхрон, и экран молчит,
      // а не печатает «Почему» под планом, который собрала модель.
      planFallbackLabel({ source: 'day-open', fallback_reason: 'llm_error' })
    ).toBeNull();
  });
});
