// [review:need-review] PHASE-03/209
// summary: desktop /health screen tests — same catalog fixture as /m/health, confirming the title frame plus the shared loading/error/sync-hint states HealthMetricGroups now owns

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import type { HealthMetric } from '@/lib/api';

const METRICS: HealthMetric[] = [
  {
    identifier: 'steps',
    kind: 'cumulative',
    canonical_unit: 'count',
    display_name: 'Шаги',
    group: 'movement',
    days: [{ date: '2026-09-05', value: 4321 }],
  },
  {
    identifier: 'heart',
    kind: 'discrete',
    canonical_unit: 'count/min',
    display_name: 'Пульс',
    group: 'heart',
    days: [],
  },
];

const ALL_EMPTY_METRICS: HealthMetric[] = METRICS.map((metric) => ({ ...metric, days: [] }));

const getMetrics = mock((_dateFrom: string, _dateTo: string) =>
  Promise.resolve({ metrics: METRICS })
);

mock.module('@/lib/api', () => ({
  healthAPI: { getMetrics: (...args: [string, string]) => getMetrics(...args) },
}));

const { default: HealthPage } = await import('./page');

afterEach(() => {
  cleanup();
  getMetrics.mockClear();
});

describe('/health', () => {
  it('shows the title and the same catalog numbers as /m/health', async () => {
    render(<HealthPage />);

    expect(screen.getByRole('heading', { name: /Health/ })).toBeDefined();
    await waitFor(() => expect(screen.getByText('Движение и энергия')).toBeDefined());
    expect(screen.getByText('Сердце и дыхание')).toBeDefined();
    expect(screen.getByText('4321 count')).toBeDefined();
    expect(screen.getByText('Нет данных')).toBeDefined();
  });

  it('shows the sync hint instead of the catalog when nothing ever synced', async () => {
    getMetrics.mockImplementationOnce(() => Promise.resolve({ metrics: ALL_EMPTY_METRICS }));
    render(<HealthPage />);

    await waitFor(() =>
      expect(
        screen.getByText('Данных ещё нет — откройте приложение на телефоне и нажмите синк.')
      ).toBeDefined()
    );
    expect(screen.queryByText('Движение и энергия')).toBeNull();
  });

  it('reports a failed load through the shared error alert', async () => {
    getMetrics.mockImplementationOnce(() => Promise.reject(new Error('network down')));
    render(<HealthPage />);

    await waitFor(() =>
      expect(screen.getByText('Не удалось загрузить данные здоровья')).toBeDefined()
    );
  });
});
