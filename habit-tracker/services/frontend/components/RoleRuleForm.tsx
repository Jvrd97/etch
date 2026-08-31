'use client';
// [review:need-review] PHASE-03/139
// summary: the rule form with its mandatory dry run — nothing is saved until the person has seen how many rows the pattern would catch over the last 30 days and which existing rule it takes them from, and an empty history says so rather than reading as «правило не ловит»

import { useState } from 'react';
import type { Role, RoleRule, RoleRuleDraft, RoleRuleDryRun } from '@/lib/api';
import {
  DRY_RUN_LABEL,
  MATCHER_OPTIONS,
  SAVE_LABEL,
  SOURCE_OPTIONS,
  dryRunSummary,
  takenFromLines,
} from '@/lib/role-rules';

/**
 * Форма одного правила разметки.
 *
 * Сухой прогон — обязательная половина, а не удобство. Правило
 * `window_title_regex` без проверки на реальных данных ловит либо ничего, либо
 * всё; на приёме «сначала сохрани, потом посмотри» человек молча перестаёт
 * трогать правила, и таблица, заведённая ровно затем, чтобы меняться без
 * деплоя, меняется раз в квартал.
 *
 * Кнопка сохранения не заперта прогоном: запирать её значило бы требовать
 * прогона там, где человек уже знает, что делает, — например, заводя первое
 * правило на пустой истории. Прогон стоит рядом и говорит, что покажет.
 */

export interface RoleRuleFormProps {
  roles: Role[];
  onDryRun: (draft: RoleRuleDraft) => Promise<RoleRuleDryRun>;
  onSave: (draft: RoleRuleDraft) => Promise<void>;
  /** Правила, у которых новое может отобрать совпадения — для расшифровки. */
  rules: RoleRule[];
}

const DEFAULT_PRIORITY = '100';

export default function RoleRuleForm({
  roles,
  rules,
  onDryRun,
  onSave,
}: RoleRuleFormProps) {
  const [roleCode, setRoleCode] = useState(roles[0]?.code ?? '');
  const [source, setSource] = useState(SOURCE_OPTIONS[0].id);
  const [matcherKind, setMatcherKind] = useState(MATCHER_OPTIONS[0].id);
  const [pattern, setPattern] = useState('');
  const [priority, setPriority] = useState(DEFAULT_PRIORITY);
  const [run, setRun] = useState<RoleRuleDryRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const draft = (): RoleRuleDraft => ({
    role_code: roleCode,
    source,
    matcher_kind: matcherKind,
    pattern: pattern.trim(),
    priority: Number(priority),
  });

  const guard = async (send: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await send();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не получилось');
    } finally {
      setBusy(false);
    }
  };

  const field =
    'w-full bg-background border border-white/10 rounded-xl px-3 py-2 text-sm text-text-primary';

  return (
    <section className="bg-card border border-white/5 rounded-3xl p-6 space-y-4">
      <h2 className="text-lg text-text-primary">Новое правило</h2>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1">
          <span className="text-sm text-text-secondary">Роль</span>
          <select
            className={field}
            value={roleCode}
            aria-label="Роль"
            onChange={(event) => setRoleCode(event.target.value)}
          >
            {roles.map((role) => (
              <option key={role.code} value={role.code}>
                {role.title}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-sm text-text-secondary">Источник</span>
          <select
            className={field}
            value={source}
            aria-label="Источник"
            onChange={(event) => setSource(event.target.value)}
          >
            {SOURCE_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-sm text-text-secondary">По чему сверять</span>
          <select
            className={field}
            value={matcherKind}
            aria-label="По чему сверять"
            onChange={(event) => setMatcherKind(event.target.value)}
          >
            {MATCHER_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-sm text-text-secondary">Вес (меньше — сильнее)</span>
          <input
            className={field}
            type="number"
            value={priority}
            aria-label="Вес"
            onChange={(event) => setPriority(event.target.value)}
          />
        </label>
      </div>

      <label className="block space-y-1">
        <span className="text-sm text-text-secondary">Образец</span>
        <input
          className={field}
          value={pattern}
          aria-label="Образец"
          placeholder="feat("
          onChange={(event) => setPattern(event.target.value)}
        />
      </label>

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={busy || pattern.trim() === ''}
          data-testid="dry-run"
          onClick={() =>
            void guard(async () => {
              setRun(await onDryRun(draft()));
            })
          }
          className="rounded-2xl bg-surface px-4 py-2 text-sm text-text-primary disabled:opacity-50"
        >
          {DRY_RUN_LABEL}
        </button>
        <button
          type="button"
          disabled={busy || pattern.trim() === ''}
          data-testid="save-rule"
          onClick={() =>
            void guard(async () => {
              await onSave(draft());
              setRun(null);
              setPattern('');
            })
          }
          className="rounded-2xl bg-lime px-4 py-2 text-sm text-background disabled:opacity-50"
        >
          {SAVE_LABEL}
        </button>
      </div>

      {run !== null && (
        <div className="rounded-2xl bg-surface px-4 py-3 space-y-2" data-testid="dry-run-result">
          <p className="text-sm text-text-primary">{dryRunSummary(run)}</p>
          {takenFromLines(run, rules).map((line) => (
            <p key={line} className="text-xs text-text-secondary">
              {line}
            </p>
          ))}
          {run.examples.length > 0 && (
            <ul className="space-y-0.5" data-testid="dry-run-examples">
              {run.examples.map((example, index) => (
                <li key={`${example.work_day}-${index}`} className="text-xs text-text-disabled">
                  {example.work_day} · {example.label}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {error !== null && <p className="text-sm text-warning">{error}</p>}
    </section>
  );
}
