// [review:need-review] #302
// summary: the desktop /insights page starts an AI analysis itself (the new dashboard no longer does) - the chosen period goes into POST /insights, the fresh report opens, a failed run shows its message, and the page no longer sends the reader to the Dashboard to start one; the api module is stubbed, no AI is called

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

interface Report {
  id: number;
  period_days: number;
  content: string;
  model: string;
  created_at: string;
}

const REPORT: Report = {
  id: 7,
  period_days: 7,
  content: 'Сон и привычки идут вместе.',
  model: 'test-model',
  created_at: '2026-10-31T09:00:00Z',
};

let created = false;
let createFails = false;
const createCalls: Array<number | undefined> = [];

// The module is replaced here, as the other page suites do: a suite earlier in the
// same run may already have swapped `@/lib/api` for a partial one, and a stubbed
// fetch would then never be reached. No AI is called either way.
mock.module('@/lib/api', () => ({
  insightsAPI: {
    create: async (periodDays?: number) => {
      createCalls.push(periodDays);
      if (createFails) throw new Error('Модель недоступна');
      created = true;
      return REPORT;
    },
    getAll: async () => (created ? [{ ...REPORT, preview: 'Сон и привычки…' }] : []),
    getById: async () => REPORT,
  },
}));

beforeEach(() => {
  created = false;
  createFails = false;
  createCalls.length = 0;
});

afterEach(() => {
  cleanup();
});

const { default: InsightsPage } = await import('./page');

describe('desktop Insights page', () => {
  it('starts an analysis over the chosen period and opens the new report', async () => {
    render(<InsightsPage />);
    const run = await screen.findByRole('button', { name: 'Запустить разбор' });

    fireEvent.click(screen.getByRole('button', { name: '7 дн.' }));
    expect(screen.getByRole('button', { name: '7 дн.' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(run);

    await waitFor(() => expect(screen.getByText('Сон и привычки идут вместе.')).toBeTruthy());
    expect(createCalls).toEqual([7]);
  });

  it('shows the message of a failed run and keeps the button usable', async () => {
    createFails = true;
    render(<InsightsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Запустить разбор' }));

    await waitFor(() => expect(screen.getByText('Модель недоступна')).toBeTruthy());
    expect(
      (screen.getByRole('button', { name: 'Запустить разбор' }) as HTMLButtonElement).disabled
    ).toBe(false);
  });

  it('does not send the reader to the Dashboard to start a run', async () => {
    render(<InsightsPage />);
    await screen.findByRole('button', { name: 'Запустить разбор' });

    expect(screen.queryByRole('link', { name: /Запустить разбор/ })).toBeNull();
    expect(screen.queryByText(/запускается с Dashboard/)).toBeNull();
  });
});
