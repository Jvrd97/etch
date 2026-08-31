'use client';
// [review:need-review] PHASE-03/158
// summary: the window-title privacy screen — the policy in the order it is applied with arrows that reorder it, a switch per rule, the number of intervals each rule touched in a week beside it, a form that adds one, and the kill switch of title collection with the warning that it erases nothing already sent

import { useState } from 'react';
import { ArrowDown, ArrowUp, Trash2, TriangleAlert } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import { useTitleRules } from '@/hooks/useTitleRules';
import type { TitleRule } from '@/lib/api';
import {
  ACTION_OPTIONS,
  ADD_RULE_LABEL,
  DOWN_LABEL,
  EMPTY_POLICY_TEXT,
  KILL_SWITCH_LABEL,
  KILL_SWITCH_WARNING,
  MATCH_KIND_OPTIONS,
  ORDER_HINT,
  UP_LABEL,
  actionLabel,
  hitsLine,
  matchKindLabel,
} from '@/lib/title-rules';

/**
 * The title policy, as a person edits it in a hurry.
 *
 * The order is drawn first and reordered with arrows, because first match wins
 * and the order is therefore meaning rather than presentation. Beside each rule
 * is what it actually did over a week: a rule with a typo in its pattern is
 * otherwise indistinguishable from one that works.
 *
 * The kill switch sits at the top with its warning attached to it, not beside
 * it. Turning off title collection stops the next title from leaving; it does
 * not erase the ones that already did, and a switch that looked like «стереть
 * всё» would one day be pressed instead of the cleanup.
 */
export default function TitleRuleList() {
  const {
    rules,
    settings,
    loading,
    saving,
    error,
    add,
    toggle,
    remove,
    move,
    setTitlesEnabled,
  } = useTitleRules();

  const [matchKind, setMatchKind] = useState<TitleRule['match_kind']>('bundle_id');
  const [pattern, setPattern] = useState('');
  const [action, setAction] = useState<TitleRule['action']>('drop');
  const [note, setNote] = useState('');

  if (loading) return <LoadingSpinner />;

  const card = 'bg-card border border-white/5 rounded-3xl p-6';
  const field =
    'w-full bg-background border border-white/10 rounded-xl px-3 py-2 text-sm text-text-primary';

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!pattern.trim()) return;
    void add({
      match_kind: matchKind,
      pattern: pattern.trim(),
      action,
      note: note.trim() || null,
    });
    setPattern('');
    setNote('');
  };

  return (
    <div className="space-y-6">
      {error && <ErrorAlert message={error} />}

      <section className={card}>
        <div className="flex items-center justify-between gap-3">
          <span className="text-text-primary">{KILL_SWITCH_LABEL}</span>
          <button
            type="button"
            disabled={saving || settings === null}
            onClick={() => void setTitlesEnabled(!(settings?.titles_enabled ?? true))}
            className="text-sm px-4 py-2 rounded-xl bg-surface text-text-primary disabled:opacity-50"
          >
            {settings?.titles_enabled ? 'выключить' : 'включить'}
          </button>
        </div>
        <p className="mt-2 inline-flex items-start gap-2 text-sm text-warning">
          <TriangleAlert className="w-4 h-4 mt-0.5 shrink-0" strokeWidth={2} />
          {KILL_SWITCH_WARNING}
        </p>
      </section>

      <section className={card}>
        <h2 className="text-text-primary text-lg">Правила заголовков</h2>
        <p className="text-sm text-text-secondary mt-1">{ORDER_HINT}</p>

        {rules.length === 0 ? (
          <p className="text-sm text-text-secondary mt-4">{EMPTY_POLICY_TEXT}</p>
        ) : (
          <ul className="space-y-3 mt-4">
            {rules.map((rule, index) => (
              <li key={rule.id} className="text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-text-primary min-w-0">
                    {matchKindLabel(rule.match_kind)} {rule.pattern} →{' '}
                    {actionLabel(rule.action)}
                    {!rule.is_active && (
                      <span className="text-xs text-text-secondary"> · выключено</span>
                    )}
                  </span>
                  <span className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      aria-label={UP_LABEL}
                      disabled={saving || index === 0}
                      onClick={() => void move(rule.id, -1)}
                      className="rounded-xl bg-surface p-1.5 text-text-secondary disabled:opacity-30"
                    >
                      <ArrowUp className="w-4 h-4" strokeWidth={2} />
                    </button>
                    <button
                      type="button"
                      aria-label={DOWN_LABEL}
                      disabled={saving || index === rules.length - 1}
                      onClick={() => void move(rule.id, 1)}
                      className="rounded-xl bg-surface p-1.5 text-text-secondary disabled:opacity-30"
                    >
                      <ArrowDown className="w-4 h-4" strokeWidth={2} />
                    </button>
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => void toggle(rule.id, !rule.is_active)}
                      className="text-xs px-2 py-1 rounded-xl border border-white/10 text-text-secondary disabled:opacity-50"
                    >
                      {rule.is_active ? 'выключить' : 'включить'}
                    </button>
                    <button
                      type="button"
                      aria-label={`Удалить правило ${rule.pattern}`}
                      disabled={saving}
                      onClick={() => void remove(rule.id)}
                      className="rounded-xl bg-surface p-1.5 text-warning disabled:opacity-50"
                    >
                      <Trash2 className="w-4 h-4" strokeWidth={2} />
                    </button>
                  </span>
                </div>
                <p className="text-xs text-text-secondary">
                  {hitsLine(rule)}
                  {rule.note ? ` · ${rule.note}` : ''}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={card}>
        <h2 className="text-text-primary text-lg mb-3">{ADD_RULE_LABEL}</h2>
        <form onSubmit={submit} className="space-y-2">
          <label className="block text-xs text-text-secondary" htmlFor="rule-kind">
            По чему совпадать
          </label>
          <select
            id="rule-kind"
            className={field}
            value={matchKind}
            onChange={(event) =>
              setMatchKind(event.target.value as TitleRule['match_kind'])
            }
          >
            {MATCH_KIND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="block text-xs text-text-secondary" htmlFor="rule-pattern">
            Шаблон
          </label>
          <input
            id="rule-pattern"
            className={field}
            type="text"
            placeholder="com.1password"
            value={pattern}
            onChange={(event) => setPattern(event.target.value)}
          />

          <label className="block text-xs text-text-secondary" htmlFor="rule-action">
            Что делать с заголовком
          </label>
          <select
            id="rule-action"
            className={field}
            value={action}
            onChange={(event) => setAction(event.target.value as TitleRule['action'])}
          >
            {ACTION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="block text-xs text-text-secondary" htmlFor="rule-note">
            Зачем правило
          </label>
          <input
            id="rule-note"
            className={field}
            type="text"
            placeholder="менеджер паролей"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />

          <button
            type="submit"
            disabled={saving}
            className="text-sm px-4 py-2 rounded-xl bg-lime text-background disabled:opacity-50"
          >
            Добавить
          </button>
        </form>
      </section>
    </div>
  );
}
