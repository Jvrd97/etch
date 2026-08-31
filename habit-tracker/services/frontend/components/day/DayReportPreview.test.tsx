// [review:need-review] PHASE-03/145
// summary: component tests for the report preview — collapsed until asked, the text and the per-source lines once opened, the revision switcher, the rebuild button, and «отчёта не собирали» told apart from a broken read

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { DayReport } from '@/lib/api';

const REPORT: DayReport = {
  day_date: '2026-08-30',
  revision: 1,
  trigger: 'button',
  content_md: '# Отчёт дня 2026-08-30\n\nW1 сделано',
  content_hash: 'a'.repeat(64),
  sources: {
    marks: { available: true, count: 2, note: '' },
    signals: { available: false, count: 0, note: 'сигналов нет — контур не подключён' },
  },
  built_at: '2026-08-30T20:00:00+00:00',
  revisions: [0, 1],
};

let asked: (number | undefined)[] = [];
let built = 0;
let failWith: unknown = null;

// Подменяется только `dayAPI`, остальной модуль остаётся настоящим: реестр
// модулей у bun общий на прогон, и подмена всего `@/lib/api` уронила бы файлы,
// которые читают из него что-то ещё.
const actual = await import('@/lib/api');
mock.module('@/lib/api', () => ({
  ...actual,
  dayAPI: {
    ...actual.dayAPI,
    getReport: (_date: string, revision?: number) => {
      asked.push(revision);
      if (failWith !== null) return Promise.reject(failWith);
      return Promise.resolve(
        revision === undefined ? REPORT : { ...REPORT, revision }
      );
    },
    buildReport: () => {
      built += 1;
      return Promise.resolve({ ...REPORT, revision: 2, revisions: [0, 1, 2] });
    },
  },
}));

const { default: DayReportPreview, REPORT_BUILD, REPORT_EXPAND, REPORT_NONE, REPORT_TITLE } =
  await import('./DayReportPreview');

afterEach(() => {
  cleanup();
  asked = [];
  built = 0;
  failWith = null;
});

describe('DayReportPreview', () => {
  it('is collapsed until somebody asks for it', () => {
    render(<DayReportPreview date="2026-08-30" />);

    expect(screen.getByText(REPORT_TITLE)).toBeDefined();
    expect(screen.getByText(REPORT_EXPAND)).toBeDefined();
    expect(asked).toEqual([]);
  });

  it('reads the report once opened and shows its text', async () => {
    render(<DayReportPreview date="2026-08-30" />);

    fireEvent.click(screen.getByText(REPORT_EXPAND));

    await waitFor(() => expect(screen.getByText(/W1 сделано/)).toBeDefined());
    expect(asked).toEqual([undefined]);
  });

  it('says of every source how much it gave and why not more', async () => {
    render(<DayReportPreview date="2026-08-30" initiallyOpen />);

    await waitFor(() => expect(screen.getByText(/отметки/)).toBeDefined());
    expect(screen.getByText(/контур не подключён/)).toBeDefined();
  });

  it('switches between revisions', async () => {
    render(<DayReportPreview date="2026-08-30" initiallyOpen />);
    await waitFor(() => expect(screen.getByText('0')).toBeDefined());

    fireEvent.click(screen.getByText('0'));

    await waitFor(() => expect(asked).toEqual([undefined, 0]));
  });

  it('rebuilds on demand', async () => {
    render(<DayReportPreview date="2026-08-30" initiallyOpen />);
    await waitFor(() => expect(screen.getByText(REPORT_BUILD)).toBeDefined());

    fireEvent.click(screen.getByText(REPORT_BUILD));

    await waitFor(() => expect(built).toBe(1));
  });

  it('tells «отчёта не собирали» from a broken read', async () => {
    // 404 — не поломка: под него рисуется кнопка сборки, а не сообщение об
    // ошибке, потому что действия у читателя разные.
    failWith = { status: 404, message: 'нет' };
    render(<DayReportPreview date="2026-08-30" initiallyOpen />);

    await waitFor(() => expect(screen.getByText(REPORT_NONE)).toBeDefined());
  });
});
