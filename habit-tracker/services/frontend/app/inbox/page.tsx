'use client';
// [review:need-review] PHASE-03/97
// summary: /inbox screen — the directory of sources with a manual «перечитать» each, the feed of signals with the link that takes a person back to the task, and the three states a source can be in told apart instead of collapsed into one grey row

import { ExternalLink, Inbox, RefreshCw } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import { useInbox } from '@/hooks/useInbox';
import { clock } from '@/lib/time';

const TITLE = 'Входящие';
const SUBTITLE =
  'Задачи и письма, пришедшие снаружи. Тела сообщений здесь не хранятся — только ссылка обратно.';

export const EMPTY_FEED = 'Ничего не приехало. Нажмите «перечитать» у источника.';
const POLL_LABEL = 'перечитать';
const DISABLED_HINT = 'не подключён';
const NO_ADAPTER_HINT = 'адаптера нет';

/** Источники без адаптера — заготовки: они в справочнике, но читать их нечем. */
const READABLE = new Set(['clickup/personal']);

export default function InboxPage() {
  const { signals, sources, loading, polling, error, poll, reload } = useInbox();

  if (loading) return <LoadingSpinner size="lg" />;

  return (
    <div className="space-y-6 animate-fade-rise">
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          {TITLE}
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">{SUBTITLE}</p>
      </div>

      {error !== null && <ErrorAlert message={error} onDismiss={reload} />}

      <section className="bg-card border border-white/5 rounded-3xl p-6">
        <h2 className="text-xl font-semibold text-text-primary">Источники</h2>
        <ul className="mt-4 space-y-2">
          {sources.map((source) => {
            const name = `${source.provider}/${source.account}`;
            const readable = READABLE.has(name);
            return (
              <li
                key={source.id}
                className="flex flex-wrap items-center gap-3 rounded-2xl px-3 py-2"
              >
                <span className="font-mono text-sm text-text-primary">{name}</span>
                {!source.is_active && (
                  <span className="text-xs text-text-disabled">{DISABLED_HINT}</span>
                )}
                {!readable && (
                  <span className="text-xs text-text-disabled">{NO_ADAPTER_HINT}</span>
                )}
                {source.last_error_code !== null && (
                  <span className="text-xs text-warning">{source.last_error_code}</span>
                )}
                <button
                  type="button"
                  onClick={() => void poll(source.id)}
                  disabled={polling !== null || !readable}
                  className="ml-auto inline-flex items-center gap-1.5 px-4 py-1.5 rounded-3xl bg-surface text-sm text-text-secondary transition-colors hover:text-text-primary disabled:opacity-40"
                >
                  <RefreshCw className="w-3.5 h-3.5" strokeWidth={2} />
                  {POLL_LABEL}
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="bg-card border border-white/5 rounded-3xl p-6">
        <h2 className="text-xl font-semibold text-text-primary">Лента</h2>
        {signals.length === 0 ? (
          <div className="mt-6 text-center py-10">
            <div className="inline-flex p-4 rounded-3xl bg-surface mb-4">
              <Inbox className="w-8 h-8 text-text-disabled" strokeWidth={2} />
            </div>
            <p className="text-text-secondary">{EMPTY_FEED}</p>
          </div>
        ) : (
          <ul className="mt-4 space-y-2">
            {signals.map((signal) => (
              <li key={signal.id} className="flex items-start gap-3 px-3 py-2">
                <span className="font-mono text-sm text-text-secondary shrink-0">
                  {clock(signal.occurred_at)}
                </span>
                <span className="min-w-0 flex-1 text-text-primary text-sm">
                  {signal.title ?? signal.external_id}
                </span>
                {signal.external_url !== null && (
                  <a
                    href={signal.external_url}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 text-text-disabled hover:text-lime"
                    aria-label="Открыть в источнике"
                  >
                    <ExternalLink className="w-4 h-4" strokeWidth={2} />
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
