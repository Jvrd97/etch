// [review:need-review] PHASE-03/114
// summary: tests for the retrieval line — the collapsed line names what was pulled and how much of it, expanding shows the exact parameters, an answer that pulled nothing renders nothing, and no data ever appears because none is carried

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ChatRetrieval } from '@/lib/api';
import ChatRetrievals from '@/components/chat/ChatRetrievals';
import { liveRetrievalLine, retrievalSummary } from '@/lib/chat-retrievals';

const SLEEP: ChatRetrieval = {
  id: 11,
  query_name: 'health_daily',
  params: { date_from: '2026-08-17', date_to: '2026-08-30' },
  row_count: 14,
  chars: 620,
  created_at: '2026-08-31T09:00:00Z',
};

const STREAK: ChatRetrieval = {
  id: 12,
  query_name: 'streak',
  params: { category_id: 3 },
  row_count: 1,
  chars: 84,
  created_at: '2026-08-31T09:00:01Z',
};

afterEach(cleanup);

describe('ChatRetrievals', () => {
  it('говорит, что было запрошено и сколько отдано, ещё до раскрытия', () => {
    render(<ChatRetrievals rows={[SLEEP]} />);

    const toggle = screen.getByTestId('retrievals-toggle');
    expect(toggle.textContent).toContain('здоровье по дням');
    expect(toggle.textContent).toContain('2026-08-17 — 2026-08-30');
    expect(toggle.textContent).toContain('14 строк');
    expect(toggle.textContent).toContain('620 знаков');
  });

  it('раскрытие показывает параметры дословно, а не пересказом', () => {
    render(<ChatRetrievals rows={[SLEEP, STREAK]} />);

    expect(screen.queryByTestId('retrievals-detail')).toBeNull();
    fireEvent.click(screen.getByTestId('retrievals-toggle'));

    const detail = screen.getByTestId('retrievals-detail');
    expect(detail.textContent).toContain('"date_from":"2026-08-17"');
    expect(detail.textContent).toContain('"category_id":3');
  });

  it('ответ, который ничего не доставал, не рисует ни строки', () => {
    const { container } = render(<ChatRetrievals rows={[]} />);

    expect(container.firstChild).toBeNull();
  });
});

describe('retrievalSummary', () => {
  it('одна дата вместо диапазона подписывается «за», а не «дата — дата»', () => {
    const line = retrievalSummary({
      ...SLEEP,
      query_name: 'day_card',
      params: { date: '2026-08-30' },
    });

    expect(line).toContain('карточка дня за 2026-08-30');
  });

  it('незнакомое имя показывается как есть, а не пропадает с экрана', () => {
    const line = retrievalSummary({ ...STREAK, query_name: 'inbox_range' });

    expect(line).toContain('inbox_range');
  });

  it('знаки названы рядом со строками: приватность считается ими', () => {
    expect(retrievalSummary(SLEEP)).toContain('620 знаков');
  });
});

describe('liveRetrievalLine', () => {
  it('идущая выборка названа тем же словом, что и сохранённая', () => {
    const line = liveRetrievalLine({
      queryName: 'health_daily',
      rowCount: 14,
      chars: 620,
      refusal: null,
    });

    expect(line).toContain('здоровье по дням');
    expect(line).toContain('14 строк');
  });

  it('отказ читается словами, а не машинным кодом', () => {
    const line = liveRetrievalLine({
      queryName: 'raw_sql',
      rowCount: 0,
      chars: 0,
      refusal: 'unknown_query',
    });

    expect(line).toContain('такого имени нет');
    expect(line).not.toContain('unknown_query');
  });
});
