'use client';
// [review:need-review] 205
// summary: «Войти по passkey» on /login — shown only where the browser can do WebAuthn and the server has passkey on; a dismissed Face ID sheet puts the button back without an error

import { useEffect, useState } from 'react';
import { Fingerprint } from 'lucide-react';
import {
  passkeyAPI,
  passkeyErrorMessage,
  passkeySupported,
  signInWithPasskey,
} from '@/lib/passkey';

type ButtonState =
  | { kind: 'hidden' }
  | { kind: 'ready' }
  | { kind: 'working' }
  | { kind: 'failed'; message: string };

/**
 * Кнопка входа по passkey.
 *
 * Скрыта, пока не доказано обратное: браузер без WebAuthn (страница по
 * `http://<IP>`) и сервер с выключенным passkey дают одну и ту же картину —
 * форму ключа, как до `#205`.
 */
export default function PasskeyLoginButton({ onSignedIn }: { onSignedIn: () => void }) {
  const [state, setState] = useState<ButtonState>({ kind: 'hidden' });

  useEffect(() => {
    if (!passkeySupported()) return;
    let alive = true;
    passkeyAPI
      .status()
      .then(({ enabled }) => {
        if (alive && enabled) setState({ kind: 'ready' });
      })
      // No answer about passkey means no passkey button; the key form stays.
      .catch(() => setState({ kind: 'hidden' }));
    return () => {
      alive = false;
    };
  }, []);

  if (state.kind === 'hidden') return null;

  const handleClick = async () => {
    if (state.kind === 'working') return;
    setState({ kind: 'working' });
    try {
      const outcome = await signInWithPasskey();
      if (outcome.status === 'cancelled') {
        setState({ kind: 'ready' });
        return;
      }
      onSignedIn();
    } catch (error) {
      setState({ kind: 'failed', message: passkeyErrorMessage(error) });
    }
  };

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={handleClick}
        disabled={state.kind === 'working'}
        className="w-full inline-flex items-center justify-center gap-2 px-4 py-3 rounded-2xl border border-lime/40 text-lime font-medium disabled:opacity-40"
      >
        <Fingerprint className="w-5 h-5" strokeWidth={2} />
        {state.kind === 'working' ? 'Ждём Face ID…' : 'Войти по passkey'}
      </button>
      {state.kind === 'failed' && (
        <p role="alert" className="text-sm text-red-400">
          {state.message}
        </p>
      )}
    </div>
  );
}
