// [review:need-review] PHASE-03/228
// summary: component tests of the week schedule screen — seven rows read Monday first over the server's Sunday-first numbers, an edit of one weekday saves the whole week, no-code is edited apart from the kind, a refused save shows its message instead of pretending, and «Сохранено» sits in a polite live region that exists before the save so a screen reader announces it

import { afterEach, describe, expect, it } from 'bun:test';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ModeSchedule } from '@/lib/api';
import ModeScheduleEditor from './ModeScheduleEditor';

afterEach(() => {
  cleanup();
});

const SEED: ModeSchedule = {
  days: [
    { weekday: 0, kind: 'dayoff', nocode: false },
    { weekday: 1, kind: 'work', nocode: false },
    { weekday: 2, kind: 'work', nocode: true },
    { weekday: 3, kind: 'work', nocode: false },
    { weekday: 4, kind: 'dayoff', nocode: true },
    { weekday: 5, kind: 'work', nocode: false },
    { weekday: 6, kind: 'work', nocode: false },
  ],
};

function show(save: (week: ModeSchedule) => Promise<ModeSchedule>) {
  const client = { read: async () => SEED, save };
  render(<ModeScheduleEditor client={client} />);
}

describe('ModeScheduleEditor', () => {
  it('lists the week from Monday and shows Tuesday as work and no-code', async () => {
    show(async (week) => week);

    await waitFor(() => expect(screen.getByLabelText('Вторник: вид дня')).toBeTruthy());
    expect((screen.getByLabelText('Вторник: вид дня') as HTMLSelectElement).value).toBe('work');
    expect((screen.getByLabelText('Вторник: no-code') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText('Воскресенье: вид дня') as HTMLSelectElement).value).toBe('dayoff');
  });

  it('saves the whole week with only the edited weekday changed', async () => {
    const saved: ModeSchedule[] = [];
    show(async (week) => {
      saved.push(week);
      return week;
    });
    await waitFor(() => expect(screen.getByLabelText('Среда: вид дня')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Среда: вид дня'), { target: { value: 'dayoff' } });
    fireEvent.click(screen.getByLabelText('Среда: no-code'));
    fireEvent.click(screen.getByText('Сохранить'));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]?.days).toHaveLength(7);
    expect(saved[0]?.days.find((d) => d.weekday === 3)).toEqual({
      weekday: 3,
      kind: 'dayoff',
      nocode: true,
    });
    expect(saved[0]?.days.find((d) => d.weekday === 2)).toEqual(SEED.days[2]!);
  });

  it('shows a refusal of the save', async () => {
    show(async () => {
      throw new Error('422');
    });
    await waitFor(() => expect(screen.getByText('Сохранить')).toBeTruthy());

    fireEvent.click(screen.getByText('Сохранить'));

    await waitFor(() => expect(screen.getByText('Не удалось сохранить расписание')).toBeTruthy());
  });

  it('announces the save through a polite live region that is there before the save', async () => {
    show(async (week) => week);
    await waitFor(() => expect(screen.getByText('Сохранить')).toBeTruthy());
    const region = screen.getByRole('status');
    expect(region.getAttribute('aria-live')).toBe('polite');
    expect(region.textContent).toBe('');

    fireEvent.click(screen.getByText('Сохранить'));

    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Сохранено'));
    expect(screen.getByRole('status')).toBe(region);
  });
});
