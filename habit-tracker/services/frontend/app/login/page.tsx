'use client';
// [review:need-review] PHASE-03/109
// summary: /login — the one screen where the key is typed; it goes out in a single request, is exchanged for an HttpOnly cookie and is never stored in the browser

import { Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { KeyRound } from 'lucide-react';
import { authAPI } from '@/lib/api';
import { NEXT_PARAM, afterLoginHref } from '@/lib/auth';

const GENERIC_FAILURE = 'Не удалось войти. Проверьте ключ и попробуйте ещё раз.';

/**
 * Форма входа.
 *
 * Ключ живёт в состоянии одного компонента ровно до отправки: в `localStorage`
 * он не кладётся ни на секунду, в URL не попадает, в ответе не возвращается.
 * Обратно приезжает `HttpOnly`-кука, которой эта страница не видит и увидеть не
 * может — в этом весь смысл (`#109`).
 */
function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting || apiKey.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      await authAPI.login(apiKey);
      // Забыть ключ до навигации: экран может не размонтироваться мгновенно.
      setApiKey('');
      router.replace(afterLoginHref(params.get(NEXT_PARAM)));
      router.refresh();
    } catch (failure) {
      setApiKey('');
      setError(failure instanceof Error && failure.message ? failure.message : GENERIC_FAILURE);
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="w-full max-w-sm bg-card border border-white/5 rounded-3xl p-6 space-y-5"
    >
      <div className="flex items-center gap-3">
        <KeyRound className="w-5 h-5 text-lime" strokeWidth={2} />
        <h1 className="text-lg font-semibold text-text-primary">Вход</h1>
      </div>

      <p className="text-sm text-text-secondary">
        Ключ отправляется один раз и обменивается на сессию. В браузере он не сохраняется.
      </p>

      <label className="block space-y-2">
        <span className="text-xs uppercase tracking-wide text-text-secondary">API-ключ</span>
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          autoComplete="off"
          autoFocus
          spellCheck={false}
          aria-label="API-ключ"
          className="w-full px-4 py-3 rounded-2xl bg-background border border-white/10 text-text-primary outline-none focus:border-lime"
        />
      </label>

      {error !== null && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={submitting || apiKey.length === 0}
        className="w-full px-4 py-3 rounded-2xl bg-lime text-background font-medium disabled:opacity-40"
      >
        {submitting ? 'Проверяем…' : 'Войти'}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      {/* useSearchParams needs a suspense boundary to keep the route static. */}
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </main>
  );
}
