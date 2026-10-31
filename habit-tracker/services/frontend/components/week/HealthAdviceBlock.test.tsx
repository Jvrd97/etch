// [review:need-review] PHASE-03/244
// summary: component tests for the «Совет» block and the supplements block of the week — the disclaimer is on screen before the advice is asked, the button states (idle, busy, ready, again), «данных мало» in words, the days the advice covers, and a week without supplements drawing no supplements block

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { HealthAdvice } from '@/lib/api';
import type { HealthAdviceClient } from '@/hooks/useHealthAdvice';
import { adherenceFixture } from '@/components/week-review/test-fixture';

const { default: HealthAdviceBlock, ADVICE_BUTTON, ADVICE_DISCLAIMER, NOT_ENOUGH_DATA_TEXT } =
  await import('./HealthAdviceBlock');
const { default: SupplementsBlock } = await import('./SupplementsBlock');

afterEach(() => {
  cleanup();
});

const ADVICE: HealthAdvice = {
  text: 'За неделю в среднем 8000 шагов.\n\nЭто не медицинская рекомендация.',
  model: 'm',
  starts_on: '2026-10-24',
  ends_on: '2026-10-30',
  days: 7,
};

function clientOf(write: () => Promise<HealthAdvice>): HealthAdviceClient & {
  asked: ReturnType<typeof mock>;
} {
  const asked = mock(write);
  return { write: () => asked(), asked };
}

describe('HealthAdviceBlock', () => {
  it('shows the disclaimer and the button before anything is asked, and asks nothing', () => {
    const client = clientOf(() => Promise.resolve(ADVICE));

    render(<HealthAdviceBlock client={client} />);

    expect(screen.getByText(ADVICE_DISCLAIMER)).toBeDefined();
    expect(screen.getByRole('button', { name: ADVICE_BUTTON })).toBeDefined();
    expect(client.asked).toHaveBeenCalledTimes(0);
  });

  it('writes the advice on the tap, shows it with its days and offers to write it again', async () => {
    const client = clientOf(() => Promise.resolve(ADVICE));
    render(<HealthAdviceBlock client={client} />);

    fireEvent.click(screen.getByRole('button', { name: ADVICE_BUTTON }));

    await waitFor(() => expect(screen.getByText(/За неделю в среднем 8000 шагов/)).toBeDefined());
    expect(client.asked).toHaveBeenCalledTimes(1);
    expect(screen.getByText('За 24.10 — 30.10 (7 дн.)', { exact: false })).toBeDefined();
    expect(screen.getByRole('button', { name: 'Написать заново' })).toBeDefined();
    expect(screen.getByText(ADVICE_DISCLAIMER)).toBeDefined();
  });

  it('disables the button while the model writes', async () => {
    const client = clientOf(() => new Promise(() => {}));
    render(<HealthAdviceBlock client={client} />);

    fireEvent.click(screen.getByRole('button', { name: ADVICE_BUTTON }));

    const busy = await screen.findByRole('button', { name: 'Пишу совет…' });
    expect(busy.hasAttribute('disabled')).toBe(true);
  });

  it('says «данных мало» in words, not as an error, when the server has too little to go on', async () => {
    const client = clientOf(() => Promise.reject({ status: 422 }));
    render(<HealthAdviceBlock client={client} />);

    fireEvent.click(screen.getByRole('button', { name: ADVICE_BUTTON }));

    await waitFor(() => expect(screen.getByText(NOT_ENOUGH_DATA_TEXT)).toBeDefined());
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows a failure of the model as an alert', async () => {
    const client = clientOf(() => Promise.reject({ status: 503 }));
    render(<HealthAdviceBlock client={client} />);

    fireEvent.click(screen.getByRole('button', { name: ADVICE_BUTTON }));

    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('Совет от ИИ выключен')
    );
  });
});

describe('SupplementsBlock', () => {
  it('prints taken of planned, the share and each supplement by name', () => {
    render(<SupplementsBlock adherence={adherenceFixture()} />);

    expect(screen.getByText('3 из 7')).toBeDefined();
    expect(screen.getByText('43%')).toBeDefined();
    expect(screen.getByText('Магний цитрат')).toBeDefined();
    expect(screen.getByText('3 из 7 дн.')).toBeDefined();
  });

  it('draws nothing for a week without supplements', () => {
    const { container } = render(<SupplementsBlock adherence={null} />);

    expect(container.innerHTML).toBe('');
  });

  it('says «данных мало» instead of a share when too few days were planned', () => {
    const adherence = { ...adherenceFixture(), enough_data: false };

    render(<SupplementsBlock adherence={adherence} />);

    expect(screen.queryByText('43%')).toBeNull();
    expect(screen.getByText('Данных мало', { exact: false })).toBeDefined();
  });
});
