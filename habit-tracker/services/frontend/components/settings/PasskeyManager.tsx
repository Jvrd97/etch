'use client';
// [review:need-review] 205
// summary: the passkey settings screen for both shells — the list (name, added, last used), «Добавить passkey» with a name field, delete after a confirm; nothing but an explanation while passkey is off on the server, no add button where the page cannot do WebAuthn

import { useCallback, useEffect, useState } from 'react';
import { Fingerprint, Trash2 } from 'lucide-react';
import {
  passkeyAPI,
  passkeyErrorMessage,
  passkeySupported,
  registerPasskey,
  type PasskeyInfo,
} from '@/lib/passkey';

/** Имя по умолчанию: ключ почти всегда добавляют с телефона. */
const DEFAULT_PASSKEY_NAME = 'iPhone';
/** Тот же предел, что у колонки `webauthn_credential.name`. */
const PASSKEY_NAME_MAX = 64;

const STAMP = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

type ScreenState =
  | { kind: 'loading' }
  | { kind: 'off' }
  | { kind: 'failed'; message: string }
  | { kind: 'ready'; passkeys: PasskeyInfo[] };

function stamp(value: string | null): string {
  return value === null ? 'ещё не использовался' : STAMP.format(new Date(value));
}

export default function PasskeyManager() {
  const [state, setState] = useState<ScreenState>({ kind: 'loading' });
  const [name, setName] = useState(DEFAULT_PASSKEY_NAME);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // Read once on mount: whether this page may call WebAuthn does not change.
  const [canAdd] = useState(() => passkeySupported());

  const load = useCallback(async () => {
    try {
      const { enabled } = await passkeyAPI.status();
      if (!enabled) {
        setState({ kind: 'off' });
        return;
      }
      setState({ kind: 'ready', passkeys: await passkeyAPI.list() });
    } catch (error) {
      setState({ kind: 'failed', message: passkeyErrorMessage(error) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAdd = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || name.trim().length === 0) return;
    setBusy(true);
    setNotice(null);
    try {
      const outcome = await registerPasskey(name.trim());
      if (outcome.status === 'done') {
        setNotice(`Passkey «${outcome.passkey.name}» добавлен.`);
        await load();
      }
    } catch (error) {
      setNotice(passkeyErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (passkey: PasskeyInfo) => {
    if (busy || !window.confirm(`Удалить passkey «${passkey.name}»? Войти им больше не получится.`)) {
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      await passkeyAPI.remove(passkey.id);
      await load();
    } catch (error) {
      setNotice(passkeyErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  if (state.kind === 'loading') {
    return <p className="text-sm text-text-secondary">Загружаем…</p>;
  }
  if (state.kind === 'off') {
    return (
      <p className="text-sm text-text-secondary">
        Passkey выключен на сервере. Он заработает, когда приложение открывается по HTTPS-имени и на
        сервере заданы WEBAUTHN_RP_ID и WEBAUTHN_ORIGINS.
      </p>
    );
  }
  if (state.kind === 'failed') {
    return (
      <p role="alert" className="text-sm text-red-400">
        {state.message}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {state.passkeys.length === 0 ? (
        <p className="text-sm text-text-secondary">Ни одного passkey пока нет.</p>
      ) : (
        <ul className="space-y-2">
          {state.passkeys.map((passkey) => (
            <li
              key={passkey.id}
              className="flex items-center gap-3 px-4 py-3 bg-card border border-white/5 rounded-2xl"
            >
              <Fingerprint className="w-5 h-5 shrink-0 text-lime" strokeWidth={2} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text-primary truncate">{passkey.name}</p>
                <p className="text-xs text-text-secondary">
                  Добавлен {stamp(passkey.created_at)} · использован {stamp(passkey.last_used_at)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => handleDelete(passkey)}
                disabled={busy}
                aria-label={`Удалить passkey ${passkey.name}`}
                className="inline-flex items-center justify-center w-10 h-10 rounded-full text-text-secondary hover:text-red-400 disabled:opacity-40"
              >
                <Trash2 className="w-4 h-4" strokeWidth={2} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {canAdd ? (
        <form onSubmit={handleAdd} className="flex flex-col sm:flex-row gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={PASSKEY_NAME_MAX}
            aria-label="Имя passkey"
            placeholder={DEFAULT_PASSKEY_NAME}
            className="flex-1 px-4 py-3 rounded-2xl bg-background border border-white/10 text-text-primary outline-none focus:border-lime"
          />
          <button
            type="submit"
            disabled={busy || name.trim().length === 0}
            className="px-4 py-3 rounded-2xl bg-lime text-background font-medium disabled:opacity-40"
          >
            {busy ? 'Ждём Face ID…' : 'Добавить passkey'}
          </button>
        </form>
      ) : (
        <p className="text-sm text-text-secondary">
          Этот адрес не умеет passkey: откройте приложение по HTTPS-имени, чтобы добавить ключ.
        </p>
      )}

      {notice !== null && (
        <p role="status" className="text-sm text-text-secondary">
          {notice}
        </p>
      )}
    </div>
  );
}
