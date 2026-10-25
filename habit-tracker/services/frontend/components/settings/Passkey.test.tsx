// [review:need-review] 205
// summary: the passkey button on /login stays hidden without WebAuthn or with passkey off on the server, and a dismissed sheet is not an error; the settings screen shows no buttons while off, and adds a key through a stubbed navigator.credentials, then lists it

import { afterEach, beforeEach, describe, expect, it, mock } from 'bun:test';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import PasskeyLoginButton from './PasskeyLoginButton';
import PasskeyManager from './PasskeyManager';

const realFetch = globalThis.fetch;

interface Answer {
  status: number;
  body: unknown;
}

let answers: Record<string, Answer[]>;
let calls: string[];

function answer(url: string, ...replies: Answer[]): void {
  answers[url] = [...(answers[url] ?? []), ...replies];
}

function setGlobal(target: object, key: string, value: unknown): void {
  Object.defineProperty(target, key, { value, configurable: true, writable: true });
}

/** Страница, на которой WebAuthn есть: безопасный контекст и `PublicKeyCredential`. */
function webauthnPage(credentials: unknown): void {
  setGlobal(window, 'isSecureContext', true);
  setGlobal(window, 'PublicKeyCredential', function PublicKeyCredential() {});
  setGlobal(navigator, 'credentials', credentials);
}

beforeEach(() => {
  answers = {};
  calls = [];
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method ?? 'GET'} ${url}`);
    const queue = answers[url] ?? [];
    const reply = queue.length > 1 ? queue.shift()! : (queue[0] ?? { status: 404, body: {} });
    return new Response(reply.status === 204 ? null : JSON.stringify(reply.body), {
      status: reply.status,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  globalThis.fetch = realFetch;
  setGlobal(window, 'isSecureContext', undefined);
  setGlobal(window, 'PublicKeyCredential', undefined);
  setGlobal(navigator, 'credentials', undefined);
});

const STATUS_URL = '/api/v1/auth/passkey/status';
const LIST_URL = '/api/v1/auth/passkeys';

function buffer(...values: number[]): ArrayBuffer {
  return new Uint8Array(values).buffer;
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe('PasskeyLoginButton', () => {
  it('is hidden where the browser has no WebAuthn, without asking the server', async () => {
    answer(STATUS_URL, { status: 200, body: { enabled: true } });
    const { container } = render(<PasskeyLoginButton onSignedIn={() => {}} />);
    await settle();
    expect(container.innerHTML).toBe('');
    expect(calls).toEqual([]);
  });

  it('is hidden when the server has passkey off', async () => {
    webauthnPage({ create: async () => null, get: async () => null });
    answer(STATUS_URL, { status: 200, body: { enabled: false } });
    const { container } = render(<PasskeyLoginButton onSignedIn={() => {}} />);
    await settle();
    expect(calls).toEqual([`GET ${STATUS_URL}`]);
    expect(container.innerHTML).toBe('');
  });

  it('puts the button back without an error when Face ID is dismissed', async () => {
    webauthnPage({
      create: async () => null,
      get: async () => {
        throw new DOMException('dismissed', 'NotAllowedError');
      },
    });
    answer(STATUS_URL, { status: 200, body: { enabled: true } });
    answer('/api/v1/auth/passkey/login/options', {
      status: 200,
      body: { options: { challenge: 'AQID', rpId: 'localhost' } },
    });
    const signedIn = mock(() => {});
    render(<PasskeyLoginButton onSignedIn={signedIn} />);

    fireEvent.click(await screen.findByText('Войти по passkey'));

    await waitFor(() => expect(screen.getByText('Войти по passkey')).toBeTruthy());
    expect(screen.queryByRole('alert')).toBeNull();
    expect(signedIn).not.toHaveBeenCalled();
  });
});

describe('PasskeyManager', () => {
  it('shows neither the list nor the add button while passkey is off', async () => {
    webauthnPage({ create: async () => null, get: async () => null });
    answer(STATUS_URL, { status: 200, body: { enabled: false } });
    render(<PasskeyManager />);
    expect(await screen.findByText(/Passkey выключен на сервере/)).toBeTruthy();
    expect(screen.queryByText('Добавить passkey')).toBeNull();
    expect(calls).toEqual([`GET ${STATUS_URL}`]);
  });

  it('adds a passkey through navigator.credentials and lists it', async () => {
    const created: CredentialCreationOptions[] = [];
    webauthnPage({
      create: async (options: CredentialCreationOptions) => {
        created.push(options);
        return {
          id: 'AQ',
          rawId: buffer(1),
          type: 'public-key',
          response: { clientDataJSON: buffer(2), attestationObject: buffer(3) },
        };
      },
      get: async () => null,
    });
    const iphone = {
      id: 1,
      name: 'iPhone',
      created_at: '2026-10-25T17:00:00Z',
      last_used_at: null,
    };
    answer(STATUS_URL, { status: 200, body: { enabled: true } });
    answer(LIST_URL, { status: 200, body: [] }, { status: 200, body: [iphone] });
    answer('/api/v1/auth/passkey/register/options', {
      status: 200,
      body: {
        options: {
          rp: { id: 'localhost', name: 'Habit Tracker' },
          user: { id: 'aGFiaXQ', name: 'habit-tracker', displayName: 'Habit Tracker' },
          challenge: 'AQID',
          pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
        },
      },
    });
    answer('/api/v1/auth/passkey/register/verify', { status: 201, body: iphone });
    render(<PasskeyManager />);

    expect(await screen.findByText('Ни одного passkey пока нет.')).toBeTruthy();
    fireEvent.click(screen.getByText('Добавить passkey'));

    expect(await screen.findByText('Passkey «iPhone» добавлен.')).toBeTruthy();
    expect(screen.getByText('iPhone')).toBeTruthy();
    expect(created).toHaveLength(1);
    expect(created[0].publicKey?.rp.id).toBe('localhost');
    expect(calls).toContain('POST /api/v1/auth/passkey/register/verify');
  });
});
