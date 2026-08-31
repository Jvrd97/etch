// [review:need-review] PHASE-03/98
// summary: source card tests — a saved key is reported as set and never rendered back, the field empties after saving, a source without an adapter offers no controls, and «перечитать» stays unavailable until the source is on and has a key

import { afterEach, describe, expect, it, mock } from 'bun:test';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { SignalSource } from '@/lib/api';
import SourceCard, {
  NO_ADAPTER,
  POLL_LABEL,
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
});
