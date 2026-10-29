// [review:need-review] PHASE-03/132
// summary: render tests of the sync-lag block — a day-old lag, a still person with a live pump, an abandoned run, a failure shown by class, and never-synced

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, screen } from '@testing-library/react';
import type { HealthSyncRun, HealthSyncStatus as Status } from '@/lib/api';
import HealthSyncStatus, { lagLabel } from './HealthSyncStatus';

afterEach(cleanup);

const RUN: HealthSyncRun = {
  sync_run_id: '3f6c1c52-0000-4000-8000-000000000001',
  kind: 'rolling',
  status: 'ok',
  interrupted: false,
  failure_kind: null,
  device_id: 'device-1',
  started_at: '2026-10-28T10:00:00Z',
  finished_at: '2026-10-28T10:00:05Z',
  range_from: null,
  range_to: null,
  samples_received: 10,
  buckets_written: 4,
  chunks_done: 1,
  chunks_total: 1,
};

function status(overrides: Partial<Status>): Status {
  return {
    last_runs: [RUN],
    last_success_at: RUN.finished_at,
    lag_hours: 0.2,
    interrupted: false,
    ...overrides,
  };
}

describe('HealthSyncStatus', () => {
  it('renders nothing before the first answer', () => {
    const { container } = render(<HealthSyncStatus status={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('names a phone dark for a day as a 24 hour lag, as a warning', () => {
    render(<HealthSyncStatus status={status({ lag_hours: 24.3 })} />);
    const block = screen.getByRole('status');
    expect(block.textContent).toContain('отставание 24 ч');
    expect(block.className).toContain('text-warning');
  });

  it('tells a live pump apart from a dark phone: under an hour, no warning', () => {
    render(<HealthSyncStatus status={status({ lag_hours: 0.2 })} />);
    const block = screen.getByRole('status');
    expect(block.textContent).toContain('меньше часа назад');
    expect(block.className).not.toContain('text-warning');
  });

  it('calls an abandoned run abandoned, not successful', () => {
    const running: HealthSyncRun = {
      ...RUN,
      status: 'running',
      interrupted: true,
      finished_at: null,
    };
    render(
      <HealthSyncStatus
        status={status({ last_runs: [running], interrupted: true, lag_hours: 5 })}
      />
    );
    expect(screen.getByRole('status').textContent).toContain('оборван');
  });

  it('shows a failure by its class, never a message', () => {
    const failed: HealthSyncRun = { ...RUN, status: 'failed', failure_kind: 'network' };
    render(<HealthSyncStatus status={status({ last_runs: [failed], lag_hours: 2 })} />);
    expect(screen.getByRole('status').textContent).toContain('нет связи с сервером');
  });

  it('says so when the pump never ran', () => {
    render(
      <HealthSyncStatus
        status={{ last_runs: [], last_success_at: null, lag_hours: null, interrupted: false }}
      />
    );
    expect(screen.getByRole('status').textContent).toContain('Синк ещё не проходил');
  });
});

describe('lagLabel', () => {
  it('rounds down to whole hours from one hour on', () => {
    expect(lagLabel(0.99)).toBe('меньше часа назад');
    expect(lagLabel(1)).toBe('отставание 1 ч');
    expect(lagLabel(47.9)).toBe('отставание 47 ч');
  });
});
