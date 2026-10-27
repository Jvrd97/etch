// [review:need-review] PHASE-03/228
// summary: component tests of the day-mode badge — kind and no-code drawn as two separate facts with who decided, a kind change keeps the no-code flag and the flag keeps the kind, the reset button exists only for a manual day, nothing is drawn while the mode is being read, a failed read says so and offers a retry

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { DayMode } from '@/lib/api';
import DayModeBadge from './DayModeBadge';

afterEach(() => {
  cleanup();
});

const TUESDAY: DayMode = { date: '2026-10-27', kind: 'work', nocode: true, source: 'schedule' };

function show(mode: DayMode | null, error: string | null = null, loadFailed = false) {
  const onDecide = mock(() => {});
  const onReset = mock(() => {});
  const onRetry = mock(() => {});
  const view = render(
    <DayModeBadge
      mode={mode}
      saving={false}
      error={error}
      loadFailed={loadFailed}
      onDecide={onDecide}
      onReset={onReset}
      onRetry={onRetry}
    />
  );
  return { ...view, onDecide, onReset, onRetry };
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

  it('says that the read failed and asks again on retry', () => {
    const { onRetry } = show(null, null, true);

    expect(screen.getByRole('alert').textContent).toContain('Не удалось прочитать режим дня');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('locks the controls while a write is in flight', () => {
    render(
      <DayModeBadge
        mode={{ ...TUESDAY, source: 'manual' }}
        saving
        error={null}
        loadFailed={false}
        onDecide={() => {}}
        onReset={() => {}}
        onRetry={() => {}}
      />
    );

    expect((screen.getByLabelText('Вид дня') as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByLabelText('no-code') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByText('Вернуть к расписанию') as HTMLButtonElement).disabled).toBe(true);
  });
});
