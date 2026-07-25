'use client';
// [review:need-review] PHASE-01/53-apply-plan-batch-endpoint
// summary: onboarding plan is now applied — checkboxes + editable names in the preview, transactional POST /categories/batch, redirect to /categories on success

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sparkles, AlertTriangle } from 'lucide-react';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import {
  categoriesAPI,
  onboardingAPI,
  type OnboardingPlan,
  type PlanField,
  type PlanOperation,
} from '@/lib/api';

// Per-operation editable state in the preview. `name` only matters for
// create_category ops; add_field ops ignore it.
interface OpState {
  enabled: boolean;
  name: string;
}

type DraftState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'done'; plan: OnboardingPlan };

type ApplyState =
  | { status: 'idle' }
  | { status: 'applying' }
  | { status: 'error'; message: string };

/**
 * Default checkbox state per the ticket: a fresh category without a name clash
 * is opted in (a stray new category is undone by one delete), while add_field
 * and anything flagged as a conflict start off — those touch data that already
 * exists, so they need a deliberate click.
 */
function initialOpStates(plan: OnboardingPlan): OpState[] {
  return plan.operations.map((op) => {
    if (op.op === 'create_category') {
      return { enabled: !op.name_conflict, name: op.name };
    }
    return { enabled: false, name: '' };
  });
}

/** Build the batch payload from the ops the user left enabled, with edited names. */
function selectedOperations(
  plan: OnboardingPlan,
  states: OpState[]
): PlanOperation[] {
  const selected: PlanOperation[] = [];
  plan.operations.forEach((op, i) => {
    const state = states[i];
    if (!state.enabled) return;
    if (op.op === 'create_category') {
      selected.push({ ...op, name: state.name });
    } else {
      selected.push(op);
    }
  });
  return selected;
}

function FieldList({ fields }: { fields: PlanField[] }) {
  if (fields.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1">
      {fields.map((field, i) => (
        <li key={i} className="text-sm text-text-secondary">
          {field.name}
          <span className="text-text-disabled"> · {field.field_type}</span>
          {field.is_required && (
            <span className="text-text-disabled"> · required</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function OperationCard({
  op,
  state,
  onToggle,
  onNameChange,
}: {
  op: PlanOperation;
  state: OpState;
  onToggle: (enabled: boolean) => void;
  onNameChange: (name: string) => void;
}) {
  return (
    <div className="bg-card border border-white/5 rounded-3xl px-6 py-5">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={state.enabled}
          onChange={(e) => onToggle(e.target.checked)}
          aria-label={
            op.op === 'create_category'
              ? `Создать категорию ${op.name}`
              : `Добавить поле ${op.field.name}`
          }
          className="mt-1.5 h-4 w-4 accent-lime shrink-0"
        />
        <div className="flex-1 min-w-0">
          {op.op === 'create_category' ? (
            <>
              <div className="flex items-center justify-between gap-3">
                <input
                  type="text"
                  value={state.name}
                  onChange={(e) => onNameChange(e.target.value)}
                  aria-label={`Имя категории ${op.name}`}
                  className="flex-1 min-w-0 bg-transparent text-base font-semibold text-text-primary focus:outline-none border-b border-transparent focus:border-lime/30"
                />
                {op.name_conflict && (
                  <span className="inline-flex items-center gap-1.5 text-xs text-danger shrink-0">
                    <AlertTriangle className="w-4 h-4" strokeWidth={2} />
                    имя уже занято
                  </span>
                )}
              </div>
              <p className="text-[13px] text-text-disabled mt-1">
                {op.display_mode} · {op.streak_mode}
                {op.group ? ` · ${op.group}` : ''}
              </p>
              <FieldList fields={op.fields} />
            </>
          ) : (
            <>
              <p className="text-base font-semibold text-text-primary">
                Новое поле в категории #{op.category_id}
              </p>
              <FieldList fields={[op.field]} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  const router = useRouter();
  const [transcript, setTranscript] = useState('');
  const [state, setState] = useState<DraftState>({ status: 'idle' });
  const [opStates, setOpStates] = useState<OpState[]>([]);
  const [applyState, setApplyState] = useState<ApplyState>({ status: 'idle' });

  const generate = async () => {
    const text = transcript.trim();
    if (!text) return;
    setState({ status: 'loading' });
    setApplyState({ status: 'idle' });
    try {
      const plan = await onboardingAPI.draft(text);
      setOpStates(initialOpStates(plan));
      setState({ status: 'done', plan });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Не удалось построить план';
      setState({ status: 'error', message });
    }
  };

  const updateOp = (index: number, patch: Partial<OpState>) => {
    setOpStates((prev) =>
      prev.map((s, i) => (i === index ? { ...s, ...patch } : s))
    );
  };

  const apply = async () => {
    if (state.status !== 'done') return;
    const operations = selectedOperations(state.plan, opStates);
    if (operations.length === 0) return;
    setApplyState({ status: 'applying' });
    try {
      await categoriesAPI.applyBatch(operations);
      router.push('/categories');
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Не удалось создать категории';
      setApplyState({ status: 'error', message });
    }
  };

  const enabledCount = opStates.filter((s) => s.enabled).length;

  return (
    <div className="space-y-8 animate-fade-rise">
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          Конструктор
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">
          Опишите словами, что хотите отслеживать — получите план и создайте
          выбранное одним нажатием.
        </p>
      </div>

      <div className="space-y-4">
        <textarea
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          rows={6}
          placeholder="Например: хочу трекать сон — сколько часов и качество, и добавить пульс в спорт"
          className="w-full bg-card border border-white/5 rounded-3xl px-5 py-4 text-text-primary placeholder:text-text-disabled focus:outline-none focus:border-lime/30 resize-y"
        />
        <button
          type="button"
          onClick={generate}
          disabled={state.status === 'loading' || transcript.trim().length === 0}
          className="inline-flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
        >
          <Sparkles className="w-4 h-4" strokeWidth={2} />
          Сгенерировать план
        </button>
      </div>

      {state.status === 'loading' && <LoadingSpinner size="lg" />}

      {state.status === 'error' && (
        <div className="space-y-4">
          <ErrorAlert message={state.message} />
          <button
            type="button"
            onClick={generate}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-colors duration-200 hover:border-lime/30"
          >
            Retry
          </button>
        </div>
      )}

      {state.status === 'done' && (
        <div className="space-y-5">
          {state.plan.operations.length === 0 ? (
            <p className="text-text-secondary">
              Модель не предложила изменений. Попробуйте описать подробнее.
            </p>
          ) : (
            <>
              {state.plan.operations.map((op, i) => (
                <OperationCard
                  key={i}
                  op={op}
                  state={opStates[i]}
                  onToggle={(enabled) => updateOp(i, { enabled })}
                  onNameChange={(name) => updateOp(i, { name })}
                />
              ))}

              {applyState.status === 'error' && (
                <ErrorAlert message={applyState.message} />
              )}

              <button
                type="button"
                onClick={apply}
                disabled={applyState.status === 'applying' || enabledCount === 0}
                className="inline-flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
              >
                {applyState.status === 'applying'
                  ? 'Создаём…'
                  : `Создать выбранное (${enabledCount})`}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
