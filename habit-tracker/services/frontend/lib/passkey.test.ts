// [review:need-review] 205
// summary: base64url round trip on bytes that hit the URL-unsafe alphabet and every padding length; server options decoded into the binary shape navigator.credentials wants; the registration flow against a stubbed navigator.credentials and fetch; a cancelled system sheet is not an error

import { afterEach, describe, expect, it, mock } from 'bun:test';
import {
  base64urlToBytes,
  bytesToBase64url,
  isPasskeyCancel,
  passkeySupported,
  registerPasskey,
  signInWithPasskey,
  toCreationOptions,
  toRequestOptions,
} from './passkey';

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
});

function bytes(...values: number[]): Uint8Array<ArrayBuffer> {
  return new Uint8Array(values);
}

describe('base64url', () => {
  it('uses the URL-safe alphabet and drops padding', () => {
    // 0xfb 0xff encodes to "+/8=" in plain base64.
    expect(bytesToBase64url(bytes(0xfb, 0xff))).toBe('-_8');
  });

  it('survives a round trip at every padding length', () => {
    for (const length of [0, 1, 2, 3, 4, 31, 32, 33]) {
      const original = Uint8Array.from({ length }, (_, index) => (index * 37 + 250) % 256);
      const decoded = base64urlToBytes(bytesToBase64url(original));
      expect(Array.from(decoded)).toEqual(Array.from(original));
    }
  });

  it('accepts an ArrayBuffer as well as a view', () => {
    expect(bytesToBase64url(bytes(1, 2, 3).buffer)).toBe('AQID');
  });
});

describe('options from the server', () => {
  it('decodes the challenge, the user id and the excluded keys for create()', () => {
    const options = toCreationOptions({
      rp: { id: 'localhost', name: 'Habit Tracker' },
      user: { id: 'aGFiaXQ', name: 'habit-tracker', displayName: 'Habit Tracker' },
      challenge: 'AQID',
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
      timeout: 300000,
      excludeCredentials: [{ id: '-_8', type: 'public-key', transports: ['internal'] }],
      authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
      attestation: 'none',
    });
    expect(Array.from(new Uint8Array(options.challenge as ArrayBuffer))).toEqual([1, 2, 3]);
    expect(new TextDecoder().decode(options.user.id as ArrayBuffer)).toBe('habit');
    const excluded = options.excludeCredentials ?? [];
    expect(Array.from(new Uint8Array(excluded[0].id as ArrayBuffer))).toEqual([0xfb, 0xff]);
    expect(excluded[0].transports).toEqual(['internal']);
    expect(options.rp.id).toBe('localhost');
  });

  it('decodes the challenge for get() and keeps the list of keys empty', () => {
    const options = toRequestOptions({
      challenge: 'AQID',
      rpId: 'localhost',
      allowCredentials: [],
      userVerification: 'required',
      timeout: 300000,
    });
    expect(Array.from(new Uint8Array(options.challenge as ArrayBuffer))).toEqual([1, 2, 3]);
    expect(options.allowCredentials).toEqual([]);
    expect(options.userVerification).toBe('required');
  });
});

describe('isPasskeyCancel', () => {
  it('treats the dismissed system sheet as a cancel, not a failure', () => {
    expect(isPasskeyCancel(new DOMException('dismissed', 'NotAllowedError'))).toBe(true);
    expect(isPasskeyCancel(new DOMException('aborted', 'AbortError'))).toBe(true);
    expect(isPasskeyCancel(new DOMException('known key', 'InvalidStateError'))).toBe(false);
    expect(isPasskeyCancel(new Error('network'))).toBe(false);
  });
});

describe('passkeySupported', () => {
  it('is false where the browser has no WebAuthn', () => {
    expect(passkeySupported({ isSecureContext: true })).toBe(false);
  });

  it('is false outside a secure context even with the API present', () => {
    expect(passkeySupported({ isSecureContext: false, PublicKeyCredential: function () {} })).toBe(
      false
    );
  });

  it('is true on a secure page with PublicKeyCredential', () => {
    expect(passkeySupported({ isSecureContext: true, PublicKeyCredential: function () {} })).toBe(
      true
    );
  });
});

interface Call {
  url: string;
  method: string;
  body: unknown;
}

function stubFetch(answers: Record<string, { status: number; body: unknown }>): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({
      url,
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    const answer = answers[url] ?? { status: 404, body: { detail: 'unexpected' } };
    return new Response(JSON.stringify(answer.body), {
      status: answer.status,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as unknown as typeof fetch;
  return calls;
}

const CREATION_OPTIONS = {
  rp: { id: 'localhost', name: 'Habit Tracker' },
  user: { id: 'aGFiaXQ', name: 'habit-tracker', displayName: 'Habit Tracker' },
  challenge: 'AQID',
  pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
  excludeCredentials: [],
  authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
};

function buffer(...values: number[]): ArrayBuffer {
  return new Uint8Array(values).buffer;
}

describe('registerPasskey', () => {
  it('asks for options, lets the authenticator create the key and sends it back encoded', async () => {
    const calls = stubFetch({
      '/api/v1/auth/passkey/register/options': { status: 200, body: { options: CREATION_OPTIONS } },
      '/api/v1/auth/passkey/register/verify': {
        status: 201,
        body: { id: 7, name: 'iPhone', created_at: '2026-10-25T17:00:00Z', last_used_at: null },
      },
    });
    let received: CredentialCreationOptions | undefined;
    const credentials = {
      create: async (options: CredentialCreationOptions) => {
        received = options;
        return {
          id: '-_8',
          rawId: buffer(0xfb, 0xff),
          type: 'public-key',
          authenticatorAttachment: 'platform',
          getClientExtensionResults: () => ({}),
          response: {
            clientDataJSON: buffer(1),
            attestationObject: buffer(2, 3),
            getTransports: () => ['internal', 'hybrid'],
          },
        };
      },
      get: async () => null,
    };

    const outcome = await registerPasskey('iPhone', credentials);

    expect(outcome).toEqual({
      status: 'done',
      passkey: { id: 7, name: 'iPhone', created_at: '2026-10-25T17:00:00Z', last_used_at: null },
    });
    expect(Array.from(new Uint8Array(received?.publicKey?.challenge as ArrayBuffer))).toEqual([
      1, 2, 3,
    ]);
    expect(calls.map((call) => [call.method, call.url])).toEqual([
      ['POST', '/api/v1/auth/passkey/register/options'],
      ['POST', '/api/v1/auth/passkey/register/verify'],
    ]);
    expect(calls[1].body).toEqual({
      name: 'iPhone',
      credential: {
        id: '-_8',
        rawId: '-_8',
        type: 'public-key',
        authenticatorAttachment: 'platform',
        clientExtensionResults: {},
        response: {
          clientDataJSON: 'AQ',
          attestationObject: 'AgM',
          transports: ['internal', 'hybrid'],
        },
      },
    });
  });

  it('reports a dismissed Face ID sheet as cancelled and sends nothing further', async () => {
    const calls = stubFetch({
      '/api/v1/auth/passkey/register/options': { status: 200, body: { options: CREATION_OPTIONS } },
    });
    const credentials = {
      create: async () => {
        throw new DOMException('dismissed', 'NotAllowedError');
      },
      get: async () => null,
    };

    expect(await registerPasskey('iPhone', credentials)).toEqual({ status: 'cancelled' });
    expect(calls).toHaveLength(1);
  });
});

describe('signInWithPasskey', () => {
  it('signs the challenge and posts the assertion without a user name', async () => {
    const calls = stubFetch({
      '/api/v1/auth/passkey/login/options': {
        status: 200,
        body: { options: { challenge: 'AQID', rpId: 'localhost', allowCredentials: [] } },
      },
      '/api/v1/auth/passkey/login/verify': {
        status: 200,
        body: { authenticated: true, expires_in_s: 2592000 },
      },
    });
    const credentials = {
      create: async () => null,
      get: async () => ({
        id: '-_8',
        rawId: buffer(0xfb, 0xff),
        type: 'public-key',
        authenticatorAttachment: 'platform',
        getClientExtensionResults: () => ({}),
        response: {
          clientDataJSON: buffer(1),
          authenticatorData: buffer(4),
          signature: buffer(5, 6),
          userHandle: buffer(7),
        },
      }),
    };

    expect(await signInWithPasskey(credentials)).toEqual({ status: 'done' });
    expect(calls[1].body).toEqual({
      credential: {
        id: '-_8',
        rawId: '-_8',
        type: 'public-key',
        authenticatorAttachment: 'platform',
        clientExtensionResults: {},
        response: {
          clientDataJSON: 'AQ',
          authenticatorData: 'BA',
          signature: 'BQY',
          userHandle: 'Bw',
        },
      },
    });
  });

  it('turns a refused sign-in into an error with the reason for the form', async () => {
    stubFetch({
      '/api/v1/auth/passkey/login/options': {
        status: 200,
        body: { options: { challenge: 'AQID', rpId: 'localhost' } },
      },
      '/api/v1/auth/passkey/login/verify': {
        status: 401,
        body: { detail: 'Passkey sign-in failed' },
      },
    });
    const credentials = {
      create: async () => null,
      get: async () => ({
        id: 'AQ',
        rawId: buffer(1),
        type: 'public-key',
        response: {
          clientDataJSON: buffer(1),
          authenticatorData: buffer(1),
          signature: buffer(1),
          userHandle: null,
        },
      }),
    };

    await expect(signInWithPasskey(credentials)).rejects.toMatchObject({ status: 401 });
  });
});
