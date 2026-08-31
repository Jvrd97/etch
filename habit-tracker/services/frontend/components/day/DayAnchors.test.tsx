// [review:need-review] PHASE-03/92
// summary: component tests for the anchors block — `relationship` is listed and ticked exactly like the edges of the day, the box walks пусто → ✓ → ✕, «неактуально» is a separate deliberate button, a kind outside this day's canon is shown as such, and the anchors the day has not closed are named rather than counted

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { DayAnchor, DayAnchors as Payload } from '@/lib/api';
import DayAnchors, {
  ANCHORS_MISSING_TITLE,
  NOT_IN_CANON,
  SKIP_LABEL,
} from './DayAnchors';

function anchor(patch: Partial<DayAnchor> = {}): DayAnchor {
  return {
    kind: 'подъём',
    title: 'подъём',
    ord: 1,
    counts_for_verdict: true,
    required_in_nonwork_evening: false,
    state: null,
    note: null,
    item_id: null,
    required_today: true,
    ...patch,
  };
}

const FAMILY: DayAnchor = anchor({
  kind: 'relationship',
  title: 'вечер с близкими',
  ord: 6,
  required_in_nonwork_evening: true,
});

function payload(patch: Partial<Payload> = {}): Payload {
  return {
    day_date: '2026-08-30',
    anchors: [anchor(), FAMILY],
    done: 0,
    total: 2,
    missing: [],
    ...patch,
  };
}

afterEach(() => {
  cleanup();
});

describe('DayAnchors', () => {
  it('lists the evening with the family beside the edges of the day', () => {
    // Приёмка тикета: третий приоритет виден в том же списке, что здоровье и
    // работа, а не отдельным «когда-нибудь потом».
    render(<DayAnchors payload={payload()} onMark={() => Promise.resolve()} />);

    expect(screen.getByText('вечер с близкими')).toBeDefined();
    expect(screen.getByText('подъём')).toBeDefined();
  });

  it('ticks the family anchor the same way as any other', async () => {
    const marked = mock((_kind: string, _state: string | null) =>
      Promise.resolve()
    );
    render(<DayAnchors payload={payload()} onMark={marked} />);

    fireEvent.click(screen.getByLabelText(/вечер с близкими/));

    await waitFor(() => expect(marked).toHaveBeenCalled());
    expect(marked.mock.calls[0]).toEqual(['relationship', 'done']);
  });

  it('walks the ring from done to failed', async () => {
    const marked = mock((_kind: string, _state: string | null) =>
      Promise.resolve()
    );
    render(
      <DayAnchors
        payload={payload({ anchors: [anchor({ state: 'done' })] })}
        onMark={marked}
      />
    );

    fireEvent.click(screen.getByLabelText(/подъём/));

    await waitFor(() => expect(marked).toHaveBeenCalled());
    expect(marked.mock.calls[0]).toEqual(['подъём', 'failed']);
  });

  it('keeps «неактуально» off the ring, as a button of its own', async () => {
    const marked = mock((_kind: string, _state: string | null) =>
      Promise.resolve()
    );
    render(
      <DayAnchors
        payload={payload({ anchors: [anchor()] })}
        onMark={marked}
      />
    );

    fireEvent.click(screen.getByText(SKIP_LABEL));

    await waitFor(() => expect(marked).toHaveBeenCalled());
    expect(marked.mock.calls[0]).toEqual(['подъём', 'skipped']);
  });

  it('says when a kind is outside the canon of this day', () => {
    render(
      <DayAnchors
        payload={payload({
          anchors: [{ ...FAMILY, required_today: false }],
          total: 1,
        })}
        onMark={() => Promise.resolve()}
      />
    );

    expect(screen.getByText(NOT_IN_CANON)).toBeDefined();
  });

  it('names the anchors the day has not closed', () => {
    render(
      <DayAnchors
        payload={payload({ missing: ['вечер с близкими'] })}
        onMark={() => Promise.resolve()}
      />
    );

    expect(screen.getByText(ANCHORS_MISSING_TITLE)).toBeDefined();
    expect(screen.getAllByText('вечер с близкими').length).toBeGreaterThan(1);
  });

  it('shows the count against the composition of the canon', () => {
    render(
      <DayAnchors
        payload={payload({ done: 5, total: 6 })}
        onMark={() => Promise.resolve()}
      />
    );

    expect(screen.getByText('5 из 6')).toBeDefined();
  });

  it('surfaces a failed write instead of pretending the anchor moved', async () => {
    render(
      <DayAnchors
        payload={payload()}
        onMark={() => Promise.reject(new Error('сеть отвалилась'))}
      />
    );

    fireEvent.click(screen.getByLabelText(/подъём/));

    await waitFor(() =>
      expect(screen.getByText('сеть отвалилась')).toBeDefined()
    );
  });
});
