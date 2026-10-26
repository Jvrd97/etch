// [review:need-review] PHASE-03/162
// summary: component tests of the day-mode badge — kind and no-code drawn as two separate facts with who decided, a kind change keeps the no-code flag and the flag keeps the kind, the reset button exists only for a manual day, and nothing is drawn before the mode is known

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { DayMode } from '@/lib/api';
import DayModeBadge from './DayModeBadge';

afterEach(() => {
  cleanup();
});

const TUESDAY: DayMode = { date: '2026-10-27', kind: 'work', nocode: true, source: 'schedule' };

function show(mode: DayMode | null, error: string | null = null) {
  const onDecide = mock(() => {});
  const onReset = mock(() => {});
  const view = render(
    <DayModeBadge mode={mode} saving={false} error={error} onDecide={onDecide} onReset={onReset} />
  );
  return { ...view, onDecide, onReset };
}

describe('DayModeBadge', () => {
  it('draws nothing before the mode is known', () => {
    const { container } = show(null);
    expect(container.textContent).toBe('');
  });

  it('shows a working no-code day and that the schedule said so', () => {
    show(TUESDAY);

    expect((screen.getByLabelText('Вид дня') as HTMLSelectElement).value).toBe('work');
    expect((screen.getByLabelText('no-code') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText('по расписанию')).toBeTruthy();
    expect(screen.queryByText('Вернуть к расписанию')).toBeNull();
  });

  it('keeps no-code when the kind changes', () => {
    const { onDecide } = show(TUESDAY);

    fireEvent.change(screen.getByLabelText('Вид дня'), { target: { value: 'vacation' } });

    expect(onDecide).toHaveBeenCalledWith('vacation', true);
  });

  it('keeps the kind when no-code flips', () => {
    const { onDecide } = show(TUESDAY);

    fireEvent.click(screen.getByLabelText('no-code'));

    expect(onDecide).toHaveBeenCalledWith('work', false);
  });

  it('offers the way back only for a day decided by hand', () => {
    const { onReset } = show({ ...TUESDAY, kind: 'sick', source: 'manual' });

    expect(screen.getByText('вручную')).toBeTruthy();
    fireEvent.click(screen.getByText('Вернуть к расписанию'));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it('says why a write failed', () => {
    show(TUESDAY, 'Не удалось сохранить режим дня');
    expect(screen.getByText('Не удалось сохранить режим дня')).toBeTruthy();
  });
});
