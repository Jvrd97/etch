'use client';
// [review:need-review] PHASE-03/158
// summary: state of the title-privacy screen — the policy and the switches read together, every write handing back the whole ordered policy so the screen never guesses the new order, and the server's refusal of a broken pattern surfaced as it came

import { useCallback, useEffect, useState } from 'react';
import { agentAPI, type AgentSettings, type TitleRule, type TitleRuleDraft } from '@/lib/api';

/** Shown when the policy cannot be read at all. */
export const LOAD_RULES_ERROR = 'Не удалось загрузить правила заголовков';

export interface UseTitleRulesResult {
  rules: TitleRule[];
  settings: AgentSettings | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  add: (draft: TitleRuleDraft) => Promise<void>;
  toggle: (id: number, isActive: boolean) => Promise<void>;
  remove: (id: number) => Promise<void>;
  move: (id: number, delta: number) => Promise<void>;
  setTitlesEnabled: (enabled: boolean) => Promise<void>;
}

/**
 * The title policy and the switches behind it.
 *
 * Every write returns the whole policy in its new order, and the screen takes
 * that answer whole rather than patching its own list. The order is what decides
 * which rule wins; a list the browser reordered by itself would show one policy
 * while the mac applied another, and that difference is exactly the kind that
 * leaks a document name.
 *
 * The error of a refused pattern is surfaced as the server worded it — it names
 * the expression and what `re` could not parse in it, which is more than a
 * frontend re-wording would.
 */
export function useTitleRules(): UseTitleRulesResult {
  const [rules, setRules] = useState<TitleRule[]>([]);
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [policy, switches] = await Promise.all([
          agentAPI.titleRules(),
          agentAPI.settings(),
        ]);
        if (cancelled) return;
        setRules(policy);
        setSettings(switches);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : LOAD_RULES_ERROR);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  /** Run one write and take the policy it hands back. Errors surface. */
  const write = useCallback(async (act: () => Promise<TitleRule[]>) => {
    setSaving(true);
    setError(null);
    try {
      setRules(await act());
    } catch (err) {
      setError(err instanceof Error ? err.message : LOAD_RULES_ERROR);
    } finally {
      setSaving(false);
    }
  }, []);

  const add = useCallback(
    (draft: TitleRuleDraft) => write(() => agentAPI.addTitleRule(draft)),
    [write]
  );

  const toggle = useCallback(
    (id: number, isActive: boolean) =>
      write(() => agentAPI.patchTitleRule(id, { is_active: isActive })),
    [write]
  );

  const remove = useCallback(
    (id: number) => write(() => agentAPI.deleteTitleRule(id)),
    [write]
  );

  const move = useCallback(
    (id: number, delta: number) => {
      const order = rules.map((rule) => rule.id);
      const from = order.indexOf(id);
      const to = from + delta;
      if (from < 0 || to < 0 || to >= order.length) return Promise.resolve();
      order.splice(to, 0, ...order.splice(from, 1));
      return write(() => agentAPI.reorderTitleRules(order));
    },
    [rules, write]
  );

  const setTitlesEnabled = useCallback(
    async (enabled: boolean) => {
      setSaving(true);
      setError(null);
      try {
        setSettings(await agentAPI.saveSettings({ titles_enabled: enabled }));
      } catch (err) {
        setError(err instanceof Error ? err.message : LOAD_RULES_ERROR);
      } finally {
        setSaving(false);
      }
    },
    []
  );

  return {
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
  };
}
