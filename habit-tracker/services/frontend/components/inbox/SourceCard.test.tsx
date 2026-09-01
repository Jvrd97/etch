// [review:need-review] PHASE-03/98, PHASE-03/191
// summary: source card tests — a saved key is reported as set and never rendered back, the field empties after saving, a source without an adapter offers no controls, «перечитать» stays unavailable until the source is on and has a key, and the probe block appears only after a press: the list with a link back, the refusal in words, and «ключ ответил, а задач нет» told apart from a failure

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { SignalSource } from '@/lib/api';
import SourceCard, {
  NEEDS_ACTIVE,
  NEEDS_SECRET,
  NOT_INGESTED,
  NO_ADAPTER,
  POLL_LABEL,
  PROBE_EMPTY,
  PROBE_LABEL,
  SAVE_LABEL,
  SECRET_MISSING,
  SECRET_SET,
} from '@/components/inbox/SourceCard';

const source = (overrides: Partial<SignalSource> = {}): SignalSource => ({
  id: 1,
  provider: 'clickup',
  account: 'personal',
  label: 'Личный ClickUp',
  direction: 'read_write',
  is_active: true,
  poll_interval_s: 900,
  credential_ref: 'CLICKUP_PERSONAL_TOKEN',
  has_secret: false,
  settings: {},
  last_polled_at: null,
  last_error_code: null,
  ...overrides,
});

function renderCard(props: Partial<React.ComponentProps<typeof SourceCard>> = {}) {
  return render(
    <SourceCard
      source={source()}
      readable
      busy={false}
      onSave={() => {}}
      onToggle={() => {}}
      onPoll={() => {}}
      onProbe={() => {}}
      probe={null}
      {...props}
    />
  );
}

afterEach(cleanup);

describe('SourceCard', () => {
  it('says whether the key is set without showing it', () => {
    // Поле, показывающее сохранённый ключ, делает его видимым каждому, кто
    // заглянул через плечо, и попадает в скриншоты.
    renderCard({ source: source({ has_secret: true }) });

    expect(screen.getByText(SECRET_SET)).toBeDefined();
    const field = screen.getByLabelText(/^Ключ/) as HTMLInputElement;
    expect(field.value).toBe('');
    expect(field.type).toBe('password');
  });

  it('says when there is no key yet', () => {
    renderCard();
    expect(screen.getByText(SECRET_MISSING)).toBeDefined();
  });

  it('sends the typed key once and clears the field', () => {
    const onSave = mock(() => {});
    renderCard({ onSave });

    const field = screen.getByLabelText(/^Ключ/) as HTMLInputElement;
    fireEvent.change(field, { target: { value: 'pk_typed_here' } });
    fireEvent.click(screen.getByRole('button', { name: SAVE_LABEL }));

    expect(onSave).toHaveBeenCalledWith('pk_typed_here', {});
    expect(field.value).toBe('');
  });

  it('carries the adapter setting beside the key', () => {
    const onSave = mock(() => {});
    renderCard({ onSave });

    fireEvent.change(screen.getByLabelText(/id воркспейса/), {
      target: { value: '90152350557' },
    });
    fireEvent.click(screen.getByRole('button', { name: SAVE_LABEL }));

    expect(onSave).toHaveBeenCalledWith(null, { team_id: '90152350557' });
  });

  it('offers no controls for a source whose adapter does not exist', () => {
    // Заготовка не притворяется рабочим источником: у Gmail и Telegram сначала
    // их тикеты, потом поля.
    renderCard({
      source: source({ provider: 'gmail', account: 'personal', label: 'Почта' }),
      readable: false,
    });

    expect(screen.getByText(NO_ADAPTER)).toBeDefined();
    expect(screen.queryByRole('button', { name: SAVE_LABEL })).toBeNull();
  });

  it('keeps «перечитать» unavailable until the source is on and has a key', () => {
    renderCard({ source: source({ is_active: true, has_secret: false }) });
    expect(
      (screen.getByRole('button', { name: POLL_LABEL }) as HTMLButtonElement).disabled
    ).toBe(true);

    cleanup();
    renderCard({ source: source({ is_active: false, has_secret: true }) });
    expect(
      (screen.getByRole('button', { name: POLL_LABEL }) as HTMLButtonElement).disabled
    ).toBe(true);

    cleanup();
    renderCard({ source: source({ is_active: true, has_secret: true }) });
    expect(
      (screen.getByRole('button', { name: POLL_LABEL }) as HTMLButtonElement).disabled
    ).toBe(false);
  });

  it('shows no probe block until the button is pressed', () => {
    // Пустая рамка на каждой карточке говорила бы о состоянии, которого нет:
    // «пробовали и ничего» и «не пробовали» — разные ответы.
    renderCard({ source: source({ has_secret: true }) });

    expect(screen.queryByTestId('probe-1')).toBeNull();
  });

  it('lists what the source sees, with a link back', () => {
    renderCard({
      source: source({ has_secret: true }),
      probe: {
        status: 'ok',
        count: 1,
        items: [
          {
            external_id: '86cb3xtv5',
            title: 'Починить сквозной flow покупки',
            external_url: 'https://app.clickup.com/t/86cb3xtv5',
            occurred_at: '2026-08-31T12:00:00Z',
          },
        ],
      },
    });

    expect(screen.getByText(/видно задач: 1/)).toBeDefined();
    const link = screen.getByText('Починить сквозной flow покупки') as HTMLAnchorElement;
    expect(link.href).toBe('https://app.clickup.com/t/86cb3xtv5');
  });

  it('says how many were left out when the ceiling cut the list', () => {
    renderCard({
      source: source({ has_secret: true }),
      probe: {
        status: 'ok',
        count: 214,
        items: [
          {
            external_id: 'a',
            title: 'первая',
            external_url: null,
            occurred_at: '2026-08-31T12:00:00Z',
          },
        ],
      },
    });

    expect(screen.getByText(/видно задач: 214 — показаны первые 1/)).toBeDefined();
  });

  it('tells an answering key with nothing to show apart from a failure', () => {
    renderCard({
      source: source({ has_secret: true }),
      probe: { status: 'ok', count: 0, items: [] },
    });

    expect(screen.getByText(PROBE_EMPTY)).toBeDefined();
  });

  it('puts the refusal in words on the card that refused', () => {
    renderCard({
      source: source({ has_secret: true }),
      probe: { status: 'failed', message: 'Источник ответил отказом.' },
    });

    expect(screen.getByText('Источник ответил отказом.')).toBeDefined();
  });

  it('offers no probe until the source is on and has a key', () => {
    renderCard({ source: source({ is_active: false, has_secret: true }) });
    expect((screen.getByText(PROBE_LABEL) as HTMLButtonElement).disabled).toBe(true);

    cleanup();
    renderCard({ source: source({ is_active: true, has_secret: false }) });
    expect((screen.getByText(PROBE_LABEL) as HTMLButtonElement).disabled).toBe(true);

    cleanup();
    renderCard({ source: source({ is_active: true, has_secret: true }) });
    expect((screen.getByText(PROBE_LABEL) as HTMLButtonElement).disabled).toBe(false);
  });

  it('asks the source when the button is pressed', () => {
    const asked = mock(() => {});
    renderCard({ source: source({ has_secret: true }), onProbe: asked });

    fireEvent.click(screen.getByText(PROBE_LABEL));

    expect(asked).toHaveBeenCalledTimes(1);
  });

  it('says why the buttons are dark instead of leaving them silent', () => {
    // Тёмная кнопка без причины — это экран, который знает ответ и молчит.
    // Порядок причин тот же, что у отказа сервера: сначала «выключен».
    renderCard({ source: source({ is_active: false, has_secret: true }) });
    expect(screen.getByText(NEEDS_ACTIVE)).toBeDefined();

    cleanup();
    renderCard({ source: source({ is_active: true, has_secret: false }) });
    expect(screen.getByText(NEEDS_SECRET)).toBeDefined();
  });

  it('stops explaining once there is nothing in the way', () => {
    renderCard({ source: source({ is_active: true, has_secret: true }) });

    expect(screen.queryByText(NEEDS_ACTIVE)).toBeNull();
    expect(screen.queryByText(NEEDS_SECRET)).toBeNull();
  });

  it('says a successful probe has not put anything into the tracker', () => {
    /*
     * Проба читает источник живьём и не пишет ни строки. Сотня задач на экране
     * выглядит как «всё приехало», а трекер при этом пуст, и следующий вопрос
     * человека — «почему чат их не видит». Экран, знающий это, обязан сказать.
     */
    renderCard({
      source: source({ has_secret: true, last_polled_at: null }),
      probe: {
        status: 'ok',
        count: 100,
        items: [
          {
            external_id: 'a',
            title: 'первая',
            external_url: null,
            occurred_at: '2026-09-01T12:00:00Z',
          },
        ],
      },
    });

    expect(screen.getByText(NOT_INGESTED)).toBeDefined();
  });

  it('stops nudging once the source has actually been read', () => {
    renderCard({
      source: source({ has_secret: true, last_polled_at: '2026-09-01T12:00:00Z' }),
      probe: { status: 'ok', count: 100, items: [] },
    });

    expect(screen.queryByText(NOT_INGESTED)).toBeNull();
  });
});
