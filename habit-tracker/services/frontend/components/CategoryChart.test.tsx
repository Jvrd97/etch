// [review:need-review] #78, PHASE-03/252, PHASE-03/264
// summary: #252 — the streak badge of a checklist category counts to the server's day (a run ending on it and a run ending the day before it)
// summary: tests for the category chart's daily averages - one per number field for the selected period, the period a trend link opens on, and equality with the dashboard Trends row for the same days

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { Category, Field, TableDay } from '@/lib/api';
import { toISODate } from '@/lib/date';
import { buildDashboardTrends, formatTrendAverage, type TrendPeriod } from '@/lib/trends';

let searchParams: URLSearchParams;

// The same four hooks every page test mocks, so a mock left behind in the
// shared registry cannot remove one that a later suite links against.
mock.module('next/navigation', () => ({
  useSearchParams: () => searchParams,
  useParams: () => ({}),
  usePathname: () => '/categories/1',
  useRouter: () => ({ push: () => {}, replace: () => {} }),
}));

// The chart is recharts inside a ResponsiveContainer, which measures a real
// layout and warns on every render when it finds none. These tests read the
// text around the chart, so the nine components CategoryChart imports are inert.
const Inert = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
mock.module('recharts', () => ({
  Bar: Inert,
  BarChart: Inert,
  CartesianGrid: Inert,
  Line: Inert,
  LineChart: Inert,
  ResponsiveContainer: Inert,
  Tooltip: Inert,
  XAxis: Inert,
  YAxis: Inert,
}));

const { default: CategoryChart } = await import('./CategoryChart');
const api = await import('@/lib/api');

const TIMESTAMP = '2026-09-01T00:00:00Z';
/** Local noon, so the calendar date never depends on the timezone of the runner. */
const NOW = new Date(2026, 8, 30, 12, 0, 0);
/**
 * Today as the dashboard code reads it. Other suites pin `todayISO` for the
 * whole run, so the days are anchored here on `toISODate(NOW)`, which they leave alone.
 */
const TODAY = toISODate(NOW);
const YEAR_OF_DAYS = 365;

function field(id: number, overrides: Partial<Field> = {}): Field {
  return {
    id,
    category_id: 1,
    name: `Field ${id}`,
    field_type: 'number',
    is_required: false,
    order: id,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    ...overrides,
  };
}

function category(fields: Field[], overrides: Partial<Category> = {}): Category {
  return {
    id: 1,
    name: 'Pushups',
    display_mode: 'form',
    streak_mode: 'build',
    is_active: true,
    created_at: TIMESTAMP,
    updated_at: TIMESTAMP,
    fields,
    ...overrides,
  };
}

/**
 * A year of days ending today, like the category page fetches. `cellsFor`
 * receives the age of a day (0 is today) and returns the cells it carries.
 */
function yearOfDays(cellsFor: (age: number) => TableDay['cells']): TableDay[] {
  return Array.from({ length: YEAR_OF_DAYS }, (_, index) => {
    const age = YEAR_OF_DAYS - 1 - index;
    const [year, month, dayOfMonth] = TODAY.split('-').map(Number);
    const date = new Date(year, month - 1, dayOfMonth - age);
    const iso = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    return { date: iso, cells: cellsFor(age) };
  });
}

function numberCell(fieldId: number, value: string | null, entryCount = 1) {
  return { category_id: 1, field_id: fieldId, aggregated_value: value, entry_count: entryCount };
}

// The server's day for the streak tests. Written onto the shared client and put back, so
// whatever other suites left in the registry is not disturbed.
type DayModeRead = () => Promise<unknown>;
const agent = api.agentAPI as unknown as { dayMode?: DayModeRead };
const realDayMode = agent.dayMode;

beforeEach(() => {
  searchParams = new URLSearchParams();
});

afterEach(() => {
  cleanup();
  agent.dayMode = realDayMode;
});

describe('CategoryChart period', () => {
  const pushups = category([field(11, { name: 'Reps', unit: 'reps' })]);
  const days = yearOfDays(() => [numberCell(11, '10')]);

  it('opens on thirty days when nothing says otherwise', () => {
    render(<CategoryChart category={pushups} days={days} />);
    expect(screen.getByRole('button', { name: '30 days', pressed: true })).toBeTruthy();
  });

  it('opens on the period a trend link carries', () => {
    searchParams = new URLSearchParams('period=7');
    render(<CategoryChart category={pushups} days={days} />);
    expect(screen.getByRole('button', { name: '7 days', pressed: true })).toBeTruthy();
  });

  it('ignores a period the trend block never offers', () => {
    searchParams = new URLSearchParams('period=14');
    render(<CategoryChart category={pushups} days={days} />);
    expect(screen.getByRole('button', { name: '30 days', pressed: true })).toBeTruthy();
  });

  it('lets the reader leave the period the link opened on', () => {
    searchParams = new URLSearchParams('period=7');
    render(<CategoryChart category={pushups} days={days} />);
    fireEvent.click(screen.getByRole('button', { name: '90 days' }));
    expect(screen.getByRole('button', { name: '90 days', pressed: true })).toBeTruthy();
  });
});

describe('CategoryChart daily averages', () => {
  it('shows an average per number field for the selected period, with its unit', () => {
    const pushups = category([
      field(11, { name: 'Reps', unit: 'reps' }),
      field(12, { name: 'Weight', unit: 'kg' }),
    ]);
    // The last 7 days carry 20 reps, the 23 before them 10: a 30-day mean of 12.3.
    const days = yearOfDays((age) => [
      numberCell(11, age < 7 ? '20' : '10'),
      numberCell(12, '5'),
    ]);

    render(<CategoryChart category={pushups} days={days} />);

    const averages = screen.getByRole('list', { name: 'Daily averages' });
    expect(within(averages).getByText('avg 12.3 reps')).toBeTruthy();
    expect(within(averages).getByText('avg 5 kg')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '7 days' }));
    expect(within(averages).getByText('avg 20 reps')).toBeTruthy();
  });

  it('leaves days without a value out of the mean instead of counting them as zero', () => {
    const pushups = category([field(11, { name: 'Reps', unit: 'reps' })]);
    const days = yearOfDays((age) => (age % 2 === 0 ? [numberCell(11, '40')] : []));

    render(<CategoryChart category={pushups} days={days} />);

    expect(screen.getByText('avg 40 reps')).toBeTruthy();
  });

  it('shows a dash for a period with nothing to average', () => {
    const pushups = category([field(11, { name: 'Reps', unit: 'reps' })]);
    render(<CategoryChart category={pushups} days={yearOfDays(() => [])} />);
    expect(screen.getByText('avg —')).toBeTruthy();
  });

  it('gives a time field no average, which the dashboard does not show either', () => {
    const sleep = category([field(11, { name: 'Slept', field_type: 'time' })]);
    render(<CategoryChart category={sleep} days={yearOfDays(() => [numberCell(11, '07:30')])} />);
    expect(screen.queryByRole('list', { name: 'Daily averages' })).toBeNull();
  });

  it('shows the same average for a checklist category with a number field', () => {
    const dose = category(
      [field(11, { name: 'Taken', field_type: 'boolean' }), field(12, { name: 'Dose', unit: 'mg' })],
      { display_mode: 'checklist' }
    );
    const days = yearOfDays((age) => [numberCell(11, 'true'), numberCell(12, age < 7 ? '4' : '2')]);
    searchParams = new URLSearchParams('period=7');

    render(<CategoryChart category={dose} days={days} />);

    expect(
      within(screen.getByRole('list', { name: 'Daily averages' })).getByText('avg 4 mg')
    ).toBeTruthy();
  });

  it('shows the averages of a checklist category that has no checkbox to chart', () => {
    const doses = category([field(12, { name: 'Dose', unit: 'mg' })], { display_mode: 'checklist' });
    render(<CategoryChart category={doses} days={yearOfDays(() => [numberCell(12, '3')])} />);

    expect(screen.getByText('avg 3 mg')).toBeTruthy();
    expect(screen.queryByText('No boolean fields to chart in this category')).toBeNull();
  });

  it('still says a checklist with no checkbox and no number has nothing to chart', () => {
    const empty = category([field(12, { name: 'Note', field_type: 'text' })], {
      display_mode: 'checklist',
    });
    render(<CategoryChart category={empty} days={[]} />);
    expect(screen.getByText('No boolean fields to chart in this category')).toBeTruthy();
  });
});

describe('CategoryChart and the dashboard agree', () => {
  const periods: TrendPeriod[] = [7, 30, 90];
  const pushups = category([field(11, { name: 'Reps', unit: 'reps' })]);
  // Uneven on purpose: gaps, a zero and drifting values, so a different window
  // or a different treatment of missing days would show up as a different number.
  const days = yearOfDays((age) => {
    if (age % 5 === 3) return [];
    if (age % 11 === 0) return [numberCell(11, '0')];
    return [numberCell(11, String(20 + ((age * 7) % 23)))];
  });

  for (const period of periods) {
    it(`prints the number the ${period}-day Trends row prints`, () => {
      // The dashboard asks for two periods ending today; the chart gets a year.
      const dashboardDays = days.slice(-period * 2);
      const [row] = buildDashboardTrends([pushups], dashboardDays, period, NOW);
      searchParams = new URLSearchParams(`period=${period}`);

      render(<CategoryChart category={pushups} days={days} />);

      expect(row).toBeDefined();
      expect(screen.getByText(`avg ${formatTrendAverage(row.average, 'reps')}`)).toBeTruthy();
    });
  }
});

describe('CategoryChart streak follows the server day (#252)', () => {
  const SERVER_DAY = '2026-09-30';
  const habit = category(
    [field(11, { name: 'Done', field_type: 'boolean' })],
    { display_mode: 'checklist' }
  );
  /** Done on the server's day and the two before it: three days in a row. */
  const doneDays = ['2026-09-30', '2026-09-29', '2026-09-28'].map((date) => ({
    date,
    cells: [numberCell(11, 'true')],
  }));

  it('counts the run to the server day, not to a browser day far from it', async () => {
    agent.dayMode = () =>
      Promise.resolve({ date: SERVER_DAY, kind: 'work', nocode: false, source: 'schedule' });
    render(<CategoryChart category={habit} days={doneDays} />);

    expect(await screen.findByText('3 days')).toBeTruthy();
  });

  it('counts a run that ends yesterday from the day the server is on', async () => {
    // The server is a day later: the run of 3 ended yesterday and is still alive.
    agent.dayMode = () =>
      Promise.resolve({ date: '2026-10-01', kind: 'work', nocode: false, source: 'schedule' });
    render(<CategoryChart category={habit} days={doneDays} />);

    expect(await screen.findByText('3 days')).toBeTruthy();
  });
});
