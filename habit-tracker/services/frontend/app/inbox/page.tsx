'use client';
// [review:need-review] PHASE-03/97
// summary: /inbox screen — every source as a card whose key is typed in here rather than into a file on the server, the feed of signals with the link that takes a person back to the task, and the states a source can be in told apart instead of collapsed into one grey row

import { ExternalLink, Inbox } from 'lucide-react';
import SourceCard from '@/components/inbox/SourceCard';
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

/**
 * Провайдеры, у которых есть адаптер.
 *
 * По провайдеру, а не по паре с аккаунтом: личный и рабочий ClickUp — один и
 * тот же API, различаются ключом и id воркспейса. Gmail и Telegram ждут своих
 * тикетов, и карточка говорит об этом прямо вместо молчаливой серой строки.
 */
const READABLE_PROVIDERS = new Set(['clickup']);

export default function InboxPage() {
  const {
    signals,
    sources,
    loading,
    polling,
    error,
    poll,
    saveCredentials,
    toggle,
    probe,
    probes,
    reload,
  } = useInbox();

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

      <div className="space-y-4">
        {sources.map((source) => (
          <SourceCard
            key={source.id}
            source={source}
            readable={READABLE_PROVIDERS.has(source.provider)}
            busy={polling !== null}
            onSave={(secret, settings) => void saveCredentials(source.id, secret, settings)}
            onToggle={(active) => void toggle(source.id, active)}
            onPoll={() => void poll(source.id)}
            onProbe={() => void probe(source.id)}
            probe={probes[source.id] ?? null}
          />
        ))}
      </div>

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
