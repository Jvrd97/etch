'use client';
// [review:need-review] PHASE-03/98
// summary: one source card — the key typed into the interface instead of into a file on the server, shown as «ключ задан» and never echoed back, the adapter's own setting beside it, the switch that turns the source on, and the reasons a source can be silent told apart

import { useState } from 'react';
import { Check, KeyRound, RefreshCw } from 'lucide-react';
import type { SignalSource } from '@/lib/api';
import { entryInputClass } from '@/lib/ui-constants';

export const SECRET_SET = 'ключ задан';
export const SECRET_MISSING = 'ключа нет';
export const SAVE_LABEL = 'Сохранить';
export const POLL_LABEL = 'перечитать';
export const NO_ADAPTER = 'адаптера нет — источник ждёт своего тикета';

/** Подпись поля настройки, по провайдеру: у каждого адаптера она своя. */
const SETTING_LABEL: Record<string, string> = {
  clickup: 'id воркспейса',
  gmail: 'лейблы через запятую',
  telegram: 'id чатов через запятую',
};

/** Ключ настройки, под которым её читает адаптер. */
const SETTING_KEY: Record<string, string> = {
  clickup: 'team_id',
  gmail: 'labels',
  telegram: 'chats',
};

export interface SourceCardProps {
  source: SignalSource;
  /** True, когда у провайдера есть адаптер: иначе кнопки бессмысленны. */
  readable: boolean;
  busy: boolean;
  onSave: (secret: string | null, settings: Record<string, string>) => void;
  onToggle: (active: boolean) => void;
  onPoll: () => void;
}

/**
 * Карточка одного источника.
 *
 * Ключ вводится здесь и уходит на сервер один раз. Обратно он не приходит
 * никогда: поле после сохранения пустеет, а рядом стоит «ключ задан». Поле,
 * показывающее сохранённый секрет, делает его видимым каждому, кто заглянул
 * через плечо, и попадает в скриншоты — поэтому его нет.
 */
export default function SourceCard({
  source,
  readable,
  busy,
  onSave,
  onToggle,
  onPoll,
}: SourceCardProps) {
  const settingKey = SETTING_KEY[source.provider] ?? 'value';
  const [secret, setSecret] = useState('');
  const [setting, setSetting] = useState(source.settings[settingKey] ?? '');

  const name = source.label ?? `${source.provider}/${source.account}`;
  const settingUnchanged = setting.trim() === (source.settings[settingKey] ?? '');

  return (
    <section className="bg-card border border-white/5 rounded-3xl p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold text-text-primary">{name}</h3>
        <span className="font-mono text-xs text-text-disabled">
          {source.provider}/{source.account}
        </span>
        {source.direction === 'read' && (
          <span className="text-xs text-text-disabled">только чтение</span>
        )}
        <span
          className={`text-xs ${source.has_secret ? 'text-lime' : 'text-text-disabled'}`}
        >
          {source.has_secret ? SECRET_SET : SECRET_MISSING}
        </span>
        {source.last_error_code !== null && (
          <span className="text-xs text-warning">{source.last_error_code}</span>
        )}
        <label className="ml-auto inline-flex items-center gap-2 text-sm text-text-secondary">
          <input
            type="checkbox"
            checked={source.is_active}
            disabled={!readable}
            onChange={(event) => onToggle(event.target.checked)}
            className="accent-lime"
          />
          включён
        </label>
      </div>

      {!readable ? (
        <p className="mt-3 text-sm text-text-disabled">{NO_ADAPTER}</p>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="block text-xs text-text-secondary mb-1">
                Ключ {source.has_secret ? '(введите, чтобы заменить)' : ''}
              </span>
              <input
                type="password"
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
                placeholder="pk_..."
                autoComplete="off"
                aria-label={`Ключ ${name}`}
                className={entryInputClass}
              />
            </label>
            <label className="block">
              <span className="block text-xs text-text-secondary mb-1">
                {SETTING_LABEL[source.provider] ?? 'настройка'}
              </span>
              <input
                type="text"
                value={setting}
                onChange={(event) => setSetting(event.target.value)}
                aria-label={`${SETTING_LABEL[source.provider] ?? 'настройка'} ${name}`}
                className={entryInputClass}
              />
            </label>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={busy || (secret.trim().length === 0 && settingUnchanged)}
              onClick={() => {
                onSave(
                  secret.trim().length > 0 ? secret.trim() : null,
                  setting.trim().length > 0 ? { [settingKey]: setting.trim() } : {}
                );
                // Поле гасится сразу: набранный ключ не должен пережить
                // сохранение ни на экране, ни в состоянии компонента.
                setSecret('');
              }}
              className="inline-flex items-center gap-2 px-5 py-2 rounded-3xl bg-lime text-background text-sm font-medium disabled:opacity-40"
            >
              <KeyRound className="w-4 h-4" strokeWidth={2} />
              {SAVE_LABEL}
            </button>

            <button
              type="button"
              onClick={onPoll}
              disabled={busy || !source.is_active || !source.has_secret}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-3xl bg-surface text-sm text-text-secondary disabled:opacity-40"
            >
              <RefreshCw className="w-3.5 h-3.5" strokeWidth={2} />
              {POLL_LABEL}
            </button>

            {source.last_polled_at !== null && (
              <span className="inline-flex items-center gap-1.5 text-xs text-text-disabled">
                <Check className="w-3.5 h-3.5" strokeWidth={2} />
                читали
              </span>
            )}
          </div>
        </>
      )}
    </section>
  );
}
