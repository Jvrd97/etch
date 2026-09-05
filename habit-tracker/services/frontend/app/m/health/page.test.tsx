// [review:need-review] PHASE-02/65
// summary: mobile Health screen tests for server grouping, values, empty metrics, and the Apple settings link

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
  {
    identifier: 'weight',
    kind: 'discrete',
    canonical_unit: 'kg',
    display_name: 'Вес',
    group: 'body',
    days: [],
  },
  {
    identifier: 'water',
    kind: 'cumulative',
    canonical_unit: 'mL',
    display_name: 'Вода',
    group: 'nutrition',
    days: [],
  },
];

mock.module('@/lib/api', () => ({
  healthAPI: { getMetrics: () => Promise.resolve({ metrics: METRICS }) },
}));

const { default: HealthPage } = await import('./page');

afterEach(cleanup);

describe('/m/health', () => {
  it('groups the server catalog and shows values or the exact empty text', async () => {
    render(<HealthPage />);

    await waitFor(() => expect(screen.getByText('Движение и энергия')).toBeDefined());
    expect(screen.getByText('Сердце и дыхание')).toBeDefined();
    expect(screen.getByText('Тело')).toBeDefined();
    expect(screen.getByText('Питание')).toBeDefined();
    expect(screen.getByText('4321 count')).toBeDefined();
    expect(screen.getAllByText('Нет данных')).toHaveLength(3);
    expect(screen.queryByText(/Доступ запрещён/i)).toBeNull();
  });

  it('links access settings to the official Apple instructions', async () => {
    render(<HealthPage />);

    const link = await screen.findByRole('link', { name: 'Настройки доступа' });
    expect(link.getAttribute('href')).toBe(
      'https://support.apple.com/guide/iphone/share-health-and-fitness-data-iph5ede58c3d/ios'
    );
  });
});
