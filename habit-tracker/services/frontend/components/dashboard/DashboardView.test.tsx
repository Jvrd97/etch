// [review:need-review] #302
// summary: tests for the dashboard view fed by the hook - skeleton while loading, all seven blocks on an answer, the day and the window named from the answer, a period switch that asks the server for the month and dims the old numbers, an empty window, a Russian error with a retry, and the mobile shell

import { afterEach, describe, expect, it } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { DashboardPeriod, DashboardSummary } from '@/lib/api';
import { emptySummary, fullSummary } from '@/test-fixtures/dashboard-summary';
import { useDashboardSummary, type DashboardSummarySource } from '@/hooks/useDashboardSummary';
import { DashboardView } from './DashboardView';

/** What a page does: the hook feeding the view. `source` stands in for the network. */
function DashboardScreen({ mobile, source }: { mobile?: boolean; source: DashboardSummarySource }) {
  const { state, period, setPeriod, reload } = useDashboardSummary(source);
  return (
    <DashboardView
      state={state}
      period={period}
      onPeriodChange={setPeriod}
      onRetry={reload}
      mobile={mobile}
    />
  );
}

afterEach(() => {
  cleanup();
});

const BLOCK_TITLES = [
  'Общий показатель',
  'Сон и пульс покоя',
  'Серии',
  'Лучшее за неделю',
  'Динамика тренировок',
  'Инсайт недели',
  'Питание · скоро',
];

describe('DashboardView', () => {
  it('shows a skeleton while the first answer is on its way', async () => {
    const source = () => new Promise<DashboardSummary>(() => {});
    render(<DashboardScreen source={source} />);

    expect(screen.getByRole('status', { name: 'Загружаем сводку' })).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Период сводки' })).toBeTruthy();
    expect(screen.queryByRole('region')).toBeNull();
  });

  it('draws every block and names the window and the server day from the answer', async () => {
    render(<DashboardScreen source={async (period) => fullSummary(period)} />);

    await waitFor(() => expect(screen.getByRole('region', { name: 'Серии' })).toBeTruthy());
    for (const title of BLOCK_TITLES) {
      expect(screen.getByRole('region', { name: title })).toBeTruthy();
    }
    expect(screen.getByText('25 окт — 31 окт · сегодня 31 окт')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Дашборд.');
  });

  it('starts on the week and asks for the month when the switch is pressed', async () => {
    const asked: DashboardPeriod[] = [];
    const source = async (period: DashboardPeriod) => {
      asked.push(period);
      return fullSummary(period);
    };
    render(<DashboardScreen source={source} />);
    await waitFor(() => expect(screen.getByRole('region', { name: 'Серии' })).toBeTruthy());

    expect(screen.getByRole('button', { name: 'Неделя' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Месяц' }));

    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'Лучшее за месяц' })).toBeTruthy()
    );
    expect(asked).toEqual(['week', 'month']);
    expect(screen.getByRole('button', { name: 'Месяц' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Неделя' }).getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByText('2 окт — 31 окт · сегодня 31 окт')).toBeTruthy();
    expect(
      within(screen.getAllByRole('link', { name: /Холодный душ/ })[0]).getByRole('img').getAttribute(
        'aria-label'
      )
    ).toContain('Последние 30 дней');
  });

  it('keeps the old numbers, dimmed and busy, until the other period arrives', async () => {
    let release: ((summary: DashboardSummary) => void) | null = null;
    const source = (period: DashboardPeriod) =>
      period === 'week'
        ? Promise.resolve(fullSummary('week'))
        : new Promise<DashboardSummary>((resolve) => {
            release = resolve;
          });
    render(<DashboardScreen source={source} />);
    await waitFor(() => expect(screen.getByRole('region', { name: 'Серии' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Месяц' }));
    const grid = screen.getByRole('region', { name: 'Серии' }).parentElement as HTMLElement;
    expect(grid.getAttribute('aria-busy')).toBe('true');
    expect(screen.getByRole('region', { name: 'Лучшее за неделю' })).toBeTruthy();

    await waitFor(() => expect(release).not.toBeNull());
    await act(async () => release?.(fullSummary('month')));
    await waitFor(() => expect(grid.getAttribute('aria-busy')).toBe('false'));
  });

  it('writes words in every block of an empty window and no zero in place of a missing number', async () => {
    render(<DashboardScreen source={async (period) => emptySummary(period)} />);

    await waitFor(() => expect(screen.getByRole('region', { name: 'Серии' })).toBeTruthy());
    expect(screen.getByText(/Серий пока нет/)).toBeTruthy();
    expect(screen.getByText(/Данных мало: сон и пульс/)).toBeTruthy();
    expect(screen.getByText(/Данных мало: лучшие значения/)).toBeTruthy();
    expect(screen.getByText(/тренировок в этом окне не записано/)).toBeTruthy();
    expect(screen.getByText(/инсайт появится/)).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Питание · скоро' })).toBeTruthy();
    expect(screen.queryByText('0')).toBeNull();
  });

  it('shows a Russian error with a retry that reads again', async () => {
    let calls = 0;
    const source = async (period: DashboardPeriod) => {
      calls += 1;
      if (calls === 1) throw new TypeError('Failed to fetch');
      return fullSummary(period);
    };
    render(<DashboardScreen source={source} />);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('проверьте соединение');
    expect(alert.textContent).not.toContain('Something went wrong');

    fireEvent.click(within(alert).getByRole('button', { name: 'Повторить' }));
    await waitFor(() => expect(screen.getByRole('region', { name: 'Серии' })).toBeTruthy());
    expect(screen.queryByRole('alert')).toBeNull();
    expect(calls).toBe(2);
  });

  it('renders the mobile shell with 44 px targets, mobile links and a screen-reader title', async () => {
    render(<DashboardScreen mobile source={async (period) => fullSummary(period)} />);

    await waitFor(() => expect(screen.getByRole('region', { name: 'Серии' })).toBeTruthy());
    expect(screen.getByRole('button', { name: 'Месяц' }).style.minHeight).toBe('44px');
    expect(screen.getAllByRole('link', { name: /Холодный душ/ })[0].getAttribute('href')).toBe(
      '/m/categories/1'
    );
    expect(screen.getByRole('heading', { level: 1 }).className).toContain('sr-only');
  });
});
