// [review:need-review] PHASE-03/238
// summary: render tests of the sleep section — the last night with its stages and the phone's own bedtime and wake time, the week of nights, the honest empty line, nothing before the answer — and the read of the seven-night window that a failure leaves out

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { HealthSleepNight } from '@/lib/api';
import { localDate } from '@/lib/health-metrics';
import SleepSection, {
  SLEEP_EMPTY_TEXT,
  nightLabel,
  sleepDuration,
  wallClock,
} from './SleepSection';
import { shiftDate, useSleepNights } from './useSleepNights';

afterEach(cleanup);

const NIGHT: HealthSleepNight = {
  date: '2026-10-20',
  bedtime: '2026-10-19T23:00:00+02:00',
  wake_time: '2026-10-20T07:00:00+02:00',
  in_bed_min: 480,
  asleep_min: 390,
  awake_min: 30,
  core_min: 210,
  deep_min: 60,
  rem_min: 120,
  unspecified_min: 0,
};

const EARLIER: HealthSleepNight = { ...NIGHT, date: '2026-10-19', asleep_min: 425 };

describe('sleep wording', () => {
  it('says hours and minutes, dropping a zero part', () => {
    expect(sleepDuration(430)).toBe('7 ч 10 мин');
    expect(sleepDuration(420)).toBe('7 ч');
    expect(sleepDuration(45)).toBe('45 мин');
    expect(sleepDuration(389.6)).toBe('6 ч 30 мин');
  });

  it('reads the time on the clock the phone lived on, not the reader one', () => {
    expect(wallClock('2026-10-19T23:40:00-04:00')).toBe('23:40');
    expect(wallClock('2026-10-20T07:05:00+02:00')).toBe('07:05');
  });

  it('names a night by its wake date', () => {
    expect(nightLabel('2026-10-20')).toContain('20');
  });
});

describe('SleepSection', () => {
  it('renders nothing before the first answer', () => {
    const { container } = render(<SleepSection nights={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('says no night arrived instead of a zero', () => {
    render(<SleepSection nights={[]} />);
    expect(screen.getByRole('status').textContent).toBe(SLEEP_EMPTY_TEXT);
    expect(screen.queryByText('0 мин')).toBeNull();
  });

  it('shows the last night with bedtime, wake time and its stages', () => {
    render(<SleepSection nights={[EARLIER, NIGHT]} />);

    expect(screen.getByRole('heading', { name: 'Сон' })).toBeDefined();
    expect(screen.getByText(/отбой 23:00, подъём 07:00/)).toBeDefined();
    expect(screen.getByText('Основной').nextSibling?.textContent).toBe('3 ч 30 мин');
    expect(screen.getByText('Глубокий').nextSibling?.textContent).toBe('1 ч');
    expect(screen.getByText('REM').nextSibling?.textContent).toBe('2 ч');
    expect(screen.getByText('Бодрствование').nextSibling?.textContent).toBe('30 мин');
    expect(screen.getByText('В кровати').nextSibling?.textContent).toBe('8 ч');
    // A stage the watch never reported is left out, not shown as zero.
    expect(screen.queryByText('Сон без фазы')).toBeNull();
  });

  it('lists every night of the week by wake date, oldest first', () => {
    render(<SleepSection nights={[EARLIER, NIGHT]} />);

    const rows = screen.getByRole('list', { name: 'Ночи недели' }).querySelectorAll('li');
    expect([...rows].map((row) => row.textContent)).toEqual([
      `${nightLabel('2026-10-19')}7 ч 5 мин`,
      `${nightLabel('2026-10-20')}6 ч 30 мин`,
    ]);
  });
});

describe('the way into the sleep detail screen', () => {
  it('links to the detail screen when the caller names one', () => {
    render(<SleepSection nights={[NIGHT]} detailHref="/health/HKCategoryTypeIdentifierSleepAnalysis" />);
    expect(screen.getByRole('link', { name: 'Все ночи' }).getAttribute('href')).toBe(
      '/health/HKCategoryTypeIdentifierSleepAnalysis'
    );
  });

  it('has no link without one', () => {
    render(<SleepSection nights={[NIGHT]} />);
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('useSleepNights', () => {
  it('asks for the range it is given', async () => {
    const asked: Array<[string, string]> = [];
    const read = (dateFrom: string, dateTo: string) => {
      asked.push([dateFrom, dateTo]);
      return Promise.resolve({ nights: [NIGHT] });
    };
    renderHook(() => useSleepNights(read, { from: '2026-09-01', to: '2026-09-30' }));
    await waitFor(() => expect(asked).toEqual([['2026-09-01', '2026-09-30']]));
  });

  it('asks for today and the six nights before it', async () => {
    const asked: Array<[string, string]> = [];
    const read = (dateFrom: string, dateTo: string) => {
      asked.push([dateFrom, dateTo]);
      return Promise.resolve({ nights: [NIGHT] });
    };

    const { result } = renderHook(() => useSleepNights(read));

    await waitFor(() => expect(result.current).toEqual([NIGHT]));
    const today = localDate();
    expect(asked).toEqual([[shiftDate(today, -6), today]]);
  });

  it('stays out after a failed read', async () => {
    let calls = 0;
    const read = () => {
      calls += 1;
      return Promise.reject(new Error('network down'));
    };

    const { result } = renderHook(() => useSleepNights(read));

    await waitFor(() => expect(calls).toBe(1));
    expect(result.current).toBeNull();
  });

  it('shifts dates across a month edge on the calendar alone', () => {
    expect(shiftDate('2026-11-02', -6)).toBe('2026-10-27');
  });
});
