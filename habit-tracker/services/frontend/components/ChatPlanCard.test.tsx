// [review:need-review] PHASE-03/115
// summary: tests for the plan card — two proposed operations become two checkboxes, unticking one narrows what is sent, an applied plan shows what was written and offers no second tap, and a dismissed or stale plan offers no buttons at all

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ChatPlan, ChatPlanSelection } from '@/lib/api';

const PROPOSED: ChatPlan = {
  id: 12,
  message_id: 5,
  entry_date: '2026-08-31',
  status: 'proposed',
  plan: {
    entry_date: '2026-08-31',
    metrics: [
      {
        op: 'log_metric',
        category_id: 1,
        field_id: 7,
        value: 30,
        source_text: 'отжался 30 раз',
      },
    ],
    checklist: [
      {
        op: 'check',
        category_id: 2,
        field_id: 9,
        source_text: 'выпил витамины',
      },
    ],
    journal: null,
  },
  operation_count: 2,
  applied_summary_id: null,
  applied_at: null,
  created_at: '2026-08-31T09:00:00Z',
};

const { default: ChatPlanCard } = await import('./ChatPlanCard');

afterEach(() => cleanup());

describe('ChatPlanCard', () => {
  it('turns «отжался 30 раз и выпил витамины» into two ticked boxes', () => {
    render(
      <ChatPlanCard plan={PROPOSED} onApply={async () => {}} onDismiss={async () => {}} />,
    );
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    expect(boxes).toHaveLength(2);
    expect(boxes.every((box) => box.checked)).toBe(true);
    expect(screen.getByText('Применить (2)')).toBeTruthy();
  });

  it('sends exactly what is still ticked', async () => {
    const seen: { planId?: number; selection?: ChatPlanSelection } = {};
    const applied = mock(async (planId: number, selection: ChatPlanSelection) => {
      seen.planId = planId;
      seen.selection = selection;
    });
    render(
      <ChatPlanCard plan={PROPOSED} onApply={applied} onDismiss={async () => {}} />,
    );

    fireEvent.click(screen.getByLabelText('выпил витамины'));
    fireEvent.click(screen.getByText('Применить (1)'));

    await waitFor(() => expect(applied).toHaveBeenCalledTimes(1));
    expect(seen.planId).toBe(12);
    expect(seen.selection?.metrics).toHaveLength(1);
    expect(seen.selection?.checklist).toHaveLength(0);
  });

  it('brings an uncertain row in unticked', () => {
    const uncertain: ChatPlan = {
      ...PROPOSED,
      plan: {
        ...PROPOSED.plan,
        metrics: [{ ...PROPOSED.plan.metrics[0], uncertain: true }],
      },
    };
    render(
      <ChatPlanCard plan={uncertain} onApply={async () => {}} onDismiss={async () => {}} />,
    );
    const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    expect(boxes[0].checked).toBe(false);
  });

  it('shows what was written and offers no second tap', () => {
    render(
      <ChatPlanCard
        plan={{
          ...PROPOSED,
          status: 'applied',
          applied_at: '2026-08-31T09:05:00Z',
          applied_summary_id: 3,
        }}
        onApply={async () => {}}
        onDismiss={async () => {}}
      />,
    );
    expect(screen.getByText(/Записано операций: 2/)).toBeTruthy();
    expect(screen.queryByText(/Применить/)).toBeNull();
    expect(screen.queryByText('Отклонить')).toBeNull();
  });

  it('says a plan of a date already applied is stale', () => {
    render(
      <ChatPlanCard
        plan={{ ...PROPOSED, status: 'stale' }}
        onApply={async () => {}}
        onDismiss={async () => {}}
      />,
    );
    expect(screen.getByText(/Устарело/)).toBeTruthy();
    expect(screen.queryByText(/Применить/)).toBeNull();
  });

  it('records the refusal instead of hiding the card', async () => {
    const dismissed = mock(async () => {});
    render(
      <ChatPlanCard plan={PROPOSED} onApply={async () => {}} onDismiss={dismissed} />,
    );
    fireEvent.click(screen.getByText('Отклонить'));
    await waitFor(() => expect(dismissed).toHaveBeenCalledTimes(1));
  });

  it('does not offer to apply nothing', () => {
    render(
      <ChatPlanCard plan={PROPOSED} onApply={async () => {}} onDismiss={async () => {}} />,
    );
    for (const box of screen.getAllByRole('checkbox')) fireEvent.click(box);
    const button = screen.getByText('Применить (0)') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});
