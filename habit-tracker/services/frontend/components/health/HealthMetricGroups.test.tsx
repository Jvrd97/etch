// [review:need-review] PHASE-03/272
// summary: the whole Apple Health catalog on the web — a metric of every group the server files (symptoms, hearing, mobility, mind, other included) prints under its own heading

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen, within } from '@testing-library/react';
import type { HealthMetric, HealthMetricGroup } from '@/lib/api';
import { HEALTH_GROUPS } from '@/lib/health-metrics';
import HealthMetricGroups from './HealthMetricGroups';

afterEach(cleanup);

function metric(group: HealthMetricGroup, displayName: string): HealthMetric {
  return {
    identifier: `id-${displayName}`,
    kind: 'cumulative',
    canonical_unit: 'count',
    display_name: displayName,
    group,
    days: [{ date: '2026-10-20', value: 1 }],
    baseline: null,
  };
}

describe('HealthMetricGroups', () => {
  it('prints a metric of every catalog group under that group heading', () => {
    const metrics = [
      metric('symptoms', 'Головная боль'),
      metric('hearing', 'Громкость в наушниках'),
      metric('mobility', 'Скорость ходьбы'),
      metric('mind', 'Минуты осознанности'),
      metric('other', 'Глюкоза крови'),
    ];

    render(<HealthMetricGroups metrics={metrics} basePath="/health" />);

    for (const [group, name] of [
      ['Симптомы', 'Головная боль'],
      ['Слух', 'Громкость в наушниках'],
      ['Подвижность', 'Скорость ходьбы'],
      ['Осознанность', 'Минуты осознанности'],
      ['Другое', 'Глюкоза крови'],
    ]) {
      const section = screen.getByRole('heading', { name: group }).closest('section');
      expect(section).not.toBeNull();
      expect(within(section as HTMLElement).getByText(name)).toBeTruthy();
    }
  });

  it('draws every group the server can file except sleep, which has its own section', () => {
    const drawn: string[] = HEALTH_GROUPS.map((group) => group.id);
    expect(drawn.sort()).toEqual(
      ['body', 'heart', 'hearing', 'mind', 'mobility', 'movement', 'nutrition', 'other', 'symptoms'].sort()
    );
  });
});
