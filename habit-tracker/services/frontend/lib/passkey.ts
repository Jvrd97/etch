// [review:need-review] 205
// summary: passkey in the browser — base64url helpers, WebAuthn options decoded for navigator.credentials and answers encoded back, the support check, the HTTP calls of /auth/passkey/* and the two flows (add a key, sign in by Face ID / Touch ID) with a dismissed system sheet reported as cancelled

/**
 * Passkey на стороне браузера (ADR-0022).
 *
 * Сервер говорит на JSON-форме WebAuthn: двоичные поля — строки base64url.
 * `navigator.credentials` хочет `ArrayBuffer`. Модуль переводит туда и обратно
 * сам, без библиотек: `PublicKeyCredential.parseCreationOptionsFromJSON` и
 * `toJSON()` есть не во всех браузерах, которыми открывают приложение.
 *
 * Запросы к `/auth/passkey/*` живут здесь, а не в `lib/api.ts`: у входа по
 * passkey свой разбор отказов (401 на входе — сообщение в форме, а не уход на
 * `/login`), и модуль не зависит от общего клиента API.
 */

import { loginRedirectTarget } from './auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

// ─── base64url ──────────────────────────────────────────────────────────────

/** Байты в base64url без `=`: так WebAuthn пишет двоичные поля в JSON. */
export function bytesToBase64url(data: ArrayBuffer | Uint8Array): string {
  const view = data instanceof Uint8Array ? data : new Uint8Array(data);
  let binary = '';
  for (const byte of view) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Обратно: base64url (с `=` или без) в байты. */
export function base64urlToBytes(text: string): Uint8Array<ArrayBuffer> {
  const base64 = text.replace(/-/g, '+').replace(/_/g, '/');
  const binary = atob(base64 + '='.repeat((4 - (base64.length % 4)) % 4));
  const out = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) out[index] = binary.charCodeAt(index);
  return out;
}

function toBuffer(text: string): ArrayBuffer {
  return base64urlToBytes(text).buffer;
}

// ─── options and answers ────────────────────────────────────────────────────

interface DescriptorJSON {
  id: string;
  type: 'public-key';
  transports?: string[];
}

/** `publicKey` для `navigator.credentials.create()` в JSON-форме сервера. */
export interface CreationOptionsJSON {
  rp: { id?: string; name: string };
  user: { id: string; name: string; displayName: string };
  challenge: string;
  pubKeyCredParams: { type: 'public-key'; alg: number }[];
  timeout?: number;
  excludeCredentials?: DescriptorJSON[];
  authenticatorSelection?: AuthenticatorSelectionCriteria;
  attestation?: AttestationConveyancePreference;
}

/** `publicKey` для `navigator.credentials.get()` в JSON-форме сервера. */
export interface RequestOptionsJSON {
  challenge: string;
  rpId?: string;
  timeout?: number;
  allowCredentials?: DescriptorJSON[];
  userVerification?: UserVerificationRequirement;
}

function toDescriptor(descriptor: DescriptorJSON): PublicKeyCredentialDescriptor {
  return {
    id: toBuffer(descriptor.id),
    type: descriptor.type,
    transports: descriptor.transports as AuthenticatorTransport[] | undefined,
  };
}

export function toCreationOptions(json: CreationOptionsJSON): PublicKeyCredentialCreationOptions {
  return {
    ...json,
    challenge: toBuffer(json.challenge),
    user: { ...json.user, id: toBuffer(json.user.id) },
    excludeCredentials: (json.excludeCredentials ?? []).map(toDescriptor),
  };
}

export function toRequestOptions(json: RequestOptionsJSON): PublicKeyCredentialRequestOptions {
  return {
    ...json,
    challenge: toBuffer(json.challenge),
    allowCredentials: (json.allowCredentials ?? []).map(toDescriptor),
  };
}

/**
 * Что из ответа аутентификатора читает этот модуль.
 *
 * Описано структурно, а не через `PublicKeyCredential`: так ответ подменяется
 * в тестах, где WebAuthn нет, и не нужен `instanceof` на классе браузера.
 */
interface CredentialLike<Response> {
  id: string;
  rawId: ArrayBuffer;
  type: string;
  authenticatorAttachment?: string | null;
  getClientExtensionResults?: () => AuthenticationExtensionsClientOutputs;
  response: Response;
}

interface AttestationLike {
  clientDataJSON: ArrayBuffer;
  attestationObject: ArrayBuffer;
  getTransports?: () => string[];
}

interface AssertionLike {
  clientDataJSON: ArrayBuffer;
  authenticatorData: ArrayBuffer;
  signature: ArrayBuffer;
  userHandle: ArrayBuffer | null;
}

function credentialJSON<R>(credential: CredentialLike<R>, response: Record<string, unknown>) {
  return {
    id: credential.id,
    rawId: bytesToBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment ?? null,
    clientExtensionResults: credential.getClientExtensionResults?.() ?? {},
    response,
  };
}

function registrationJSON(credential: CredentialLike<AttestationLike>) {
  const { response } = credential;
  return credentialJSON(credential, {
    clientDataJSON: bytesToBase64url(response.clientDataJSON),
    attestationObject: bytesToBase64url(response.attestationObject),
    transports: response.getTransports?.() ?? [],
  });
}

function authenticationJSON(credential: CredentialLike<AssertionLike>) {
  const { response } = credential;
  return credentialJSON(credential, {
    clientDataJSON: bytesToBase64url(response.clientDataJSON),
    authenticatorData: bytesToBase64url(response.authenticatorData),
    signature: bytesToBase64url(response.signature),
    userHandle: response.userHandle === null ? null : bytesToBase64url(response.userHandle),
  });
}

// ─── support and cancel ─────────────────────────────────────────────────────

interface PasskeyEnvironment {
  isSecureContext?: boolean;
  PublicKeyCredential?: unknown;
}

/**
 * Умеет ли эта страница WebAuthn.
 *
 * Только безопасный контекст: HTTPS или `localhost`. На `http://<IP>:3000`
 * браузер не даёт `PublicKeyCredential` вовсе, и кнопка там была бы обманом.
 */
export function passkeySupported(
  env: PasskeyEnvironment | undefined = typeof window === 'undefined' ? undefined : window
): boolean {
  return env?.isSecureContext === true && typeof env.PublicKeyCredential === 'function';
}

/**
 * Закрыл ли человек системное окно (Face ID, «Отмена»).
 *
 * Браузер не отличает отмену от тайм-аута — оба `NotAllowedError`, — и ни то
 * ни другое не ошибка, о которой стоит кричать красным.
 */
export function isPasskeyCancel(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    (error.name === 'NotAllowedError' || error.name === 'AbortError')
  );
}

// ─── HTTP ───────────────────────────────────────────────────────────────────

/** Ключ в списке настроек. */
export interface PasskeyInfo {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

export class PasskeyRequestError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'PasskeyRequestError';
  }
}

/**
 * Who answers a 401: the login screen (`signed-in` calls lost their session) or
 * the caller (a sign-in ceremony, where 401 means "this passkey did not fit").
 */
type OnUnauthorized = 'go-to-login' | 'caller';

async function request<T>(
  path: string,
  init?: RequestInit,
  onUnauthorized: OnUnauthorized = 'go-to-login'
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    if (onUnauthorized === 'go-to-login' && typeof window !== 'undefined') {
      const target = loginRedirectTarget(
        response.status,
        window.location.pathname,
        window.location.search
      );
      if (target !== null) window.location.assign(target);
    }
    const body: unknown = await response.json().catch(() => null);
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `HTTP ${response.status}`;
    throw new PasskeyRequestError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function post<T>(path: string, body?: unknown, onUnauthorized?: OnUnauthorized): Promise<T> {
  const init = { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) };
  return request<T>(path, init, onUnauthorized);
}

export const passkeyAPI = {
  status: () => request<{ enabled: boolean }>('/auth/passkey/status', undefined, 'caller'),
  list: () => request<PasskeyInfo[]>('/auth/passkeys'),
  remove: (id: number) => request<void>(`/auth/passkeys/${id}`, { method: 'DELETE' }),
};

// ─── flows ──────────────────────────────────────────────────────────────────

/** `navigator.credentials` или его подмена в тестах. */
export interface PasskeyCredentials {
  create(options: CredentialCreationOptions): Promise<unknown>;
  get(options: CredentialRequestOptions): Promise<unknown>;
}

/** Итоги церемоний: сделано или человек закрыл системное окно. */
export type RegisterOutcome = { status: 'done'; passkey: PasskeyInfo } | { status: 'cancelled' };
export type SignInOutcome = { status: 'done' } | { status: 'cancelled' };

function browserCredentials(): PasskeyCredentials {
  return navigator.credentials;
}

async function ceremony<T>(run: () => Promise<unknown>): Promise<T | null> {
  try {
    const credential = await run();
    if (credential === null || typeof credential !== 'object') return null;
    return credential as T;
  } catch (error) {
    if (isPasskeyCancel(error)) return null;
    throw error;
  }
}

/** Добавить passkey этого устройства под именем `name` (уже вошедший клиент). */
export async function registerPasskey(
  name: string,
  credentials: PasskeyCredentials = browserCredentials()
): Promise<RegisterOutcome> {
  const { options } = await post<{ options: CreationOptionsJSON }>('/auth/passkey/register/options');
  const credential = await ceremony<CredentialLike<AttestationLike>>(() =>
    credentials.create({ publicKey: toCreationOptions(options) })
  );
  if (credential === null) return { status: 'cancelled' };
  const passkey = await post<PasskeyInfo>('/auth/passkey/register/verify', {
    name,
    credential: registrationJSON(credential),
  });
  return { status: 'done', passkey };
}

/** Войти по passkey: окно Face ID / Touch ID, затем та же сессионная кука, что и по ключу. */
export async function signInWithPasskey(
  credentials: PasskeyCredentials = browserCredentials()
): Promise<SignInOutcome> {
  const { options } = await post<{ options: RequestOptionsJSON }>(
    '/auth/passkey/login/options',
    undefined,
    'caller'
  );
  const credential = await ceremony<CredentialLike<AssertionLike>>(() =>
    credentials.get({ publicKey: toRequestOptions(options) })
  );
  if (credential === null) return { status: 'cancelled' };
  await post('/auth/passkey/login/verify', { credential: authenticationJSON(credential) }, 'caller');
  return { status: 'done' };
}

/** Фраза для человека вместо кода ответа или имени исключения браузера. */
export function passkeyErrorMessage(error: unknown): string {
  if (error instanceof DOMException && error.name === 'InvalidStateError') {
    return 'Этот passkey уже добавлен на этом устройстве.';
  }
  if (error instanceof PasskeyRequestError) {
    if (error.status === 401) return 'Passkey не подошёл. Попробуйте ещё раз или войдите по ключу.';
    if (error.status === 409) return 'Этот passkey уже добавлен.';
    if (error.status === 503) return 'Passkey не настроен на сервере.';
    if (error.status === 400) return 'Сервер не принял passkey. Попробуйте ещё раз.';
  }
  return 'Не получилось. Попробуйте ещё раз.';
}
