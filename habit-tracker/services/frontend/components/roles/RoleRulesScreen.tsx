'use client';
// [review:need-review] PHASE-03/139
// summary: the rules screen both shells draw — the markup as rows in the order the resolver picks a winner in, the form with its mandatory dry run, and the re-markup of a period with its before/after

import { useCallback, useEffect, useState } from 'react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import RoleReclassifyPanel from '@/components/RoleReclassifyPanel';
import RoleRuleForm from '@/components/RoleRuleForm';
import { rolesAPI, type Role, type RoleRule, type RoleRuleDraft } from '@/lib/api';
import { defaultRange } from '@/lib/role-rules';

/**
 * Правила разметки: список, форма и переразметка.
 *
 * Один экран на обе оболочки, как и всё остальное здесь. Список идёт в том
 * порядке, в котором резолвер выбирает победителя — меньший `priority`, при
 * равенстве меньший id, — потому что «какое правило сильнее» человек читает
 * глазами по списку, а не выводит из чисел.
 *
 * Границы переразметки берутся от дня, который назвал сервер (`/roles/day`), а
 * не от календаря браузера: сутки начинаются в 4:00.
 */

export const EMPTY_RULES_TEXT =
  'Правил разметки пока нет: заведите первое — оно начнёт действовать на следующей же разметке.';

export interface RoleRulesScreenProps {
  compact?: boolean;
}

export default function RoleRulesScreen({ compact = false }: RoleRulesScreenProps) {
  const [roles, setRoles] = useState<Role[]>([]);
  const [rules, setRules] = useState<RoleRule[]>([]);
  const [today, setToday] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [directory, markup, day] = await Promise.all([
      rolesAPI.listRoles(),
      rolesAPI.listRules(),
      rolesAPI.day(),
    ]);
    setRoles(directory);
    setRules(markup);
    setToday(day.work_day);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await reload();
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Не загрузилось');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  if (loading) return <LoadingSpinner size="lg" />;
  if (error !== null) return <ErrorAlert message={error} />;

  const range = defaultRange(today ?? new Date().toISOString().slice(0, 10));
  const card = `bg-card border border-white/5 rounded-3xl ${compact ? 'p-4' : 'p-6'}`;

  const save = async (draft: RoleRuleDraft) => {
    await rolesAPI.addRule(draft);
    await reload();
  };

  return (
    <div className={compact ? 'space-y-4' : 'space-y-6'}>
      <section className={card}>
        <h2 className="text-lg text-text-primary">Правила разметки</h2>
        {rules.length === 0 ? (
          <p className="mt-3 text-text-secondary">{EMPTY_RULES_TEXT}</p>
        ) : (
          <ul className="mt-3 space-y-2" data-testid="rules-list">
            {rules.map((rule) => (
              <li
                key={rule.id}
                className="flex flex-wrap items-baseline justify-between gap-2 text-sm"
              >
                <span className="text-text-primary">
                  {rule.priority} · {rule.pattern}
                </span>
                <span className="text-text-secondary">
                  {rule.source} → {rule.role_code}
                  {!rule.is_active && ' · выключено'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {roles.length > 0 && (
        <RoleRuleForm
          roles={roles}
          rules={rules}
          onDryRun={(draft) => rolesAPI.dryRunRule(draft)}
          onSave={save}
        />
      )}

      <RoleReclassifyPanel
        roles={roles}
        defaultFrom={range.from}
        defaultTo={range.to}
        onReclassify={(from, to) => rolesAPI.reclassify(from, to)}
      />
    </div>
  );
}
