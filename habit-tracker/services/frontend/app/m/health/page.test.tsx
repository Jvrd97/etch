// [review:need-review] PHASE-02/65, PHASE-03/209, PHASE-03/238, PHASE-02/68
// summary: mobile Health screen tests for server grouping, values, the Apple settings link, the whole-catalog sync hint and a failed load — all through the shared useHealthMetrics/HealthMetricGroups now behind this page; the sleep section above the catalog and the catalog surviving a failed sleep read

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import type { HealthMetric, HealthSleepNight } from '@/lib/api';

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

const ALL_EMPTY_METRICS: HealthMetric[] = METRICS.map((metric) => ({ ...metric, days: [] }));

// Mutable so each scenario below can answer the one request this page makes
// without redeclaring the module mock — the default is the mixed catalog every
// earlier test already relied on.
const getMetrics = mock((_dateFrom: string, _dateTo: string) =>
  Promise.resolve({ metrics: METRICS })
);

const NIGHT: HealthSleepNight = {
  date: '2026-09-05',
  bedtime: '2026-09-04T23:40:00+02:00',
  wake_time: '2026-09-05T07:10:00+02:00',
  in_bed_min: 450,
  asleep_min: 430,
  awake_min: 20,
  core_min: 250,
  deep_min: 80,
  rem_min: 100,
  unspecified_min: 0,
};

const getSleep = mock(() => Promise.resolve({ nights: [NIGHT] }));

mock.module('@/lib/api', () => ({
  healthAPI: {
    getMetrics: (...args: [string, string]) => getMetrics(...args),
    getSleep: () => getSleep(),
  },
}));

const { default: HealthPage } = await import('./page');

afterEach(() => {
  cleanup();
  getMetrics.mockClear();
  getSleep.mockClear();
});

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

  it('shows the sync hint instead of a wall of empty rows when nothing ever synced', async () => {
    getMetrics.mockImplementationOnce(() => Promise.resolve({ metrics: ALL_EMPTY_METRICS }));
    render(<HealthPage />);

    await waitFor(() =>
      expect(
        screen.getByText('Данных ещё нет — откройте приложение на телефоне и нажмите синк.')
      ).toBeDefined()
    );
    expect(screen.queryByText('Движение и энергия')).toBeNull();
    expect(screen.queryByText('Нет данных')).toBeNull();
  });

  it('reports a failed load instead of hanging on the spinner', async () => {
    getMetrics.mockImplementationOnce(() => Promise.reject(new Error('network down')));
    render(<HealthPage />);

    await waitFor(() =>
      expect(screen.getByText('Не удалось загрузить данные здоровья')).toBeDefined()
    );
  });

  it('shows last night above the catalog, on the phone clock', async () => {
    render(<HealthPage />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Сон' })).toBeDefined());
    expect(screen.getAllByText('7 ч 10 мин').length).toBeGreaterThan(0);
    expect(screen.getByText(/отбой 23:40, подъём 07:10/)).toBeDefined();
    expect(getSleep).toHaveBeenCalledTimes(1);
  });

  it('keeps the catalog when the sleep read fails', async () => {
    getSleep.mockImplementationOnce(() => Promise.reject(new Error('network down')));
    render(<HealthPage />);

    await waitFor(() => expect(screen.getByText('4321 count')).toBeDefined());
    expect(screen.queryByRole('heading', { name: 'Сон' })).toBeNull();
  });

  it('links every catalog row to its detail screen', async () => {
    render(<HealthPage />);

    await waitFor(() => expect(screen.getByText('4321 count')).toBeDefined());
    expect(screen.getByRole('link', { name: /Шаги/ }).getAttribute('href')).toBe('/m/health/steps');
  });
});
