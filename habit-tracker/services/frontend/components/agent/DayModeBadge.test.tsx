// [review:need-review] PHASE-03/249, PHASE-03/257
// summary: component tests of the day-mode badge — kind and no-code drawn as two separate facts with who decided, a kind change keeps the no-code flag and the flag keeps the kind, the reset button exists only for a manual day, nothing is drawn while the mode is being read, a failed read says so and offers a retry, also over a mode already on screen (locked, since it may be yesterday's), the controls are locked while a re-read is on its way; since #257 locked means `aria-disabled` and not `disabled` (a disabled select drops keyboard focus when the window is focused again and the controls are re-enabled), a locked control does nothing, a read in progress is `aria-busy` and says so once it is slow

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { DayMode } from '@/lib/api';
import DayModeBadge, { type DayModeBadgeProps } from './DayModeBadge';

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
      reading={false}
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
        reading={false}
        error={null}
        loadFailed={false}
        onDecide={() => {}}
        onReset={() => {}}
        onRetry={() => {}}
      />
    );

    expect(screen.getByLabelText('Вид дня').getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByLabelText('no-code').getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByText('Вернуть к расписанию').getAttribute('aria-disabled')).toBe('true');
  });

  it('locks the controls while a read is on its way', () => {
    render(
      <DayModeBadge
        mode={{ ...TUESDAY, source: 'manual' }}
        saving={false}
        reading
        error={null}
        loadFailed={false}
        onDecide={() => {}}
        onReset={() => {}}
        onRetry={() => {}}
      />
    );

    expect(screen.getByLabelText('Вид дня').getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByLabelText('no-code').getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByText('Вернуть к расписанию').getAttribute('aria-disabled')).toBe('true');
  });

  it('says the re-read failed over the old mode, locks the controls and offers a retry', () => {
    const { onRetry } = show({ ...TUESDAY, source: 'manual' }, null, true);

    expect(screen.getByRole('alert').textContent).toContain('Не удалось прочитать режим дня');
    expect(screen.getByLabelText('Вид дня').getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByLabelText('no-code').getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByText('Вернуть к расписанию').getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('does not use the disabled attribute, so keyboard focus survives a lock', () => {
    const view = render(<Badge locked="reading" />);
    const select = screen.getByLabelText('Вид дня') as HTMLSelectElement;
    select.focus();
    expect(document.activeElement).toBe(select);

    view.rerender(<Badge locked="reading" />);
    view.rerender(<Badge locked={null} />);

    expect(select.disabled).toBe(false);
    expect(document.activeElement).toBe(select);
  });

  it('does nothing when a locked control is used', () => {
    const onDecide = mock(() => {});
    const onReset = mock(() => {});
    render(
      <Badge locked="reading" mode={{ ...TUESDAY, source: 'manual' }} onDecide={onDecide} onReset={onReset} />
    );

    fireEvent.change(screen.getByLabelText('Вид дня'), { target: { value: 'sick' } });
    fireEvent.click(screen.getByLabelText('no-code'));
    fireEvent.click(screen.getByText('Вернуть к расписанию'));

    expect(onDecide).not.toHaveBeenCalled();
    expect(onReset).not.toHaveBeenCalled();
    // The controls show the mode of the server, not the attempt.
    expect((screen.getByLabelText('Вид дня') as HTMLSelectElement).value).toBe('work');
    expect((screen.getByLabelText('no-code') as HTMLInputElement).checked).toBe(true);
  });

  it('marks the badge busy while it reads or saves, and not otherwise', () => {
    const view = render(<Badge locked="reading" />);
    expect(screen.getByLabelText('Вид дня').closest('[aria-busy]')?.getAttribute('aria-busy')).toBe('true');

    view.rerender(<Badge locked="saving" />);
    expect(screen.getByLabelText('Вид дня').closest('[aria-busy]')?.getAttribute('aria-busy')).toBe('true');

    view.rerender(<Badge locked={null} />);
    expect(screen.getByLabelText('Вид дня').closest('[aria-busy]')?.getAttribute('aria-busy')).toBe('false');
  });

  it('stays quiet during a short read and says it is reading when the read is slow', async () => {
    const view = render(<Badge locked="reading" slowReadMs={30} />);
    expect(screen.queryByText('Читаю режим дня…')).toBeNull();
    expect(screen.getByLabelText('Вид дня').className).not.toContain('opacity-50');

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Читаю режим дня…'));
    expect(screen.getByLabelText('Вид дня').className).toContain('opacity-50');

    view.rerender(<Badge locked={null} slowReadMs={30} />);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('dims the controls while saving or after a failed read, not during a short read', () => {
    const view = render(<Badge locked="saving" />);
    expect(screen.getByLabelText('Вид дня').className).toContain('opacity-50');

    view.rerender(<Badge locked="reading" />);
    expect(screen.getByLabelText('Вид дня').className).not.toContain('opacity-50');

    view.rerender(<Badge locked="loadFailed" />);
    expect(screen.getByLabelText('Вид дня').className).toContain('opacity-50');
  });
});

type Lock = 'reading' | 'saving' | 'loadFailed' | null;

function Badge({
  locked,
  mode = TUESDAY,
  slowReadMs,
  onDecide = () => {},
  onReset = () => {},
}: {
  locked: Lock;
  mode?: DayMode;
  slowReadMs?: number;
  onDecide?: DayModeBadgeProps['onDecide'];
  onReset?: () => void;
}) {
  return (
    <DayModeBadge
      mode={mode}
      saving={locked === 'saving'}
      reading={locked === 'reading'}
      error={null}
      loadFailed={locked === 'loadFailed'}
      onDecide={onDecide}
      onReset={onReset}
      onRetry={() => {}}
      slowReadMs={slowReadMs}
    />
  );
}
