'use client';
// [review:need-review] PHASE-03/139
// summary: the re-markup panel — a date range, the button that applies today's rules to a month already laid out, and the before/after of the shares with the number of rows a person had confirmed and nothing touched

import { useState } from 'react';
import type { Role, RoleReclassified } from '@/lib/api';
import {
  RECLASSIFY_LABEL,
  protectedLine,
  reclassifyLines,
} from '@/lib/role-rules';

/**
 * Переразметка периода задним числом.
 *
 * Без неё правило, добавленное сегодня, размечает только завтрашние строки, и
 * месяц, разложенный неверно, так неверным и остаётся — то есть срабатывает
 * названный в ADR сигнал «автоматика не работает», хотя не работает не
 * автоматика, а невозможность её починить задним числом.
 *
 * Число защищённых записей стоит рядом с результатом, а не в подсказке:
 * «ничего не изменилось» и «изменилось всё, кроме ваших правок» — разные
 * исходы одной кнопки.
 */

export interface RoleReclassifyPanelProps {
  roles: Role[];
  /** Границы по умолчанию: месяц, кончающийся сегодняшним днём сервера. */
  defaultFrom: string;
  defaultTo: string;
  onReclassify: (from: string, to: string) => Promise<RoleReclassified>;
}

export default function RoleReclassifyPanel({
  roles,
  defaultFrom,
  defaultTo,
  onReclassify,
}: RoleReclassifyPanelProps) {
  const [from, setFrom] = useState(defaultFrom);
  const [to, setTo] = useState(defaultTo);
  const [result, setResult] = useState<RoleReclassified | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const field =
    'bg-background border border-white/10 rounded-xl px-3 py-2 text-sm text-text-primary';

  return (
    <section className="bg-card border border-white/5 rounded-3xl p-6 space-y-4">
      <h2 className="text-lg text-text-primary">Переразметить период</h2>

      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1">
          <span className="text-sm text-text-secondary">С</span>
          <input
            className={field}
            type="date"
            value={from}
            aria-label="С"
            onChange={(event) => setFrom(event.target.value)}
          />
        </label>
        <label className="space-y-1">
          <span className="text-sm text-text-secondary">По</span>
          <input
            className={field}
            type="date"
            value={to}
            aria-label="По"
            onChange={(event) => setTo(event.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={busy}
          data-testid="reclassify"
          onClick={() => {
            setBusy(true);
            setError(null);
            void (async () => {
              try {
                setResult(await onReclassify(from, to));
              } catch (err) {
                setError(err instanceof Error ? err.message : 'Не получилось');
              } finally {
                setBusy(false);
              }
            })();
          }}
          className="rounded-2xl bg-surface px-4 py-2 text-sm text-text-primary disabled:opacity-50"
        >
          {RECLASSIFY_LABEL}
        </button>
      </div>

      {result !== null && (
        <div className="rounded-2xl bg-surface px-4 py-3 space-y-1" data-testid="reclassify-result">
          <p className="text-sm text-text-primary" data-testid="reclassify-protected">
            {protectedLine(result)}
          </p>
          {reclassifyLines(result, roles).map((line) => (
            <p key={line} className="text-xs text-text-secondary">
              {line}
            </p>
          ))}
        </div>
      )}

      {error !== null && <p className="text-sm text-warning">{error}</p>}
    </section>
  );
}
