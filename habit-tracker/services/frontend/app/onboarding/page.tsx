'use client';
// [review:need-review] PHASE-01/62-mobile-onboarding-twin
// summary: desktop voice-category-builder — markup only; the draft/preview/apply flow moved into useOnboardingPlan, which /m/onboarding renders with its own layout

import { useRouter } from 'next/navigation';
import { Sparkles, AlertTriangle } from 'lucide-react';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import { useOnboardingPlan, type OpState } from '@/hooks/useOnboardingPlan';
import type { PlanField, PlanOperation } from '@/lib/api';

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
  const plan = useOnboardingPlan({ onApplied: () => router.push('/categories') });
  const generate = () => void plan.generate();

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
          value={plan.transcript}
          onChange={(e) => plan.setTranscript(e.target.value)}
          rows={6}
          placeholder="Например: хочу трекать сон — сколько часов и качество, и добавить пульс в спорт"
          className="w-full bg-card border border-white/5 rounded-3xl px-5 py-4 text-text-primary placeholder:text-text-disabled focus:outline-none focus:border-lime/30 resize-y"
        />
        <button
          type="button"
          onClick={generate}
          disabled={!plan.canGenerate}
          className="inline-flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
        >
          <Sparkles className="w-4 h-4" strokeWidth={2} />
          Сгенерировать план
        </button>
      </div>

      {plan.draft.status === 'loading' && <LoadingSpinner size="lg" />}

      {plan.draft.status === 'error' && (
        <div className="space-y-4">
          <ErrorAlert message={plan.draft.message} />
          <button
            type="button"
            onClick={generate}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-colors duration-200 hover:border-lime/30"
          >
            Retry
          </button>
        </div>
      )}

      {plan.draft.status === 'done' && (
        <div className="space-y-5">
          {plan.draft.plan.operations.length === 0 ? (
            <p className="text-text-secondary">
              Модель не предложила изменений. Попробуйте описать подробнее.
            </p>
          ) : (
            <>
              {plan.draft.plan.operations.map((op, i) => (
                <OperationCard
                  key={i}
                  op={op}
                  state={plan.opStates[i]}
                  onToggle={(enabled) => plan.updateOp(i, { enabled })}
                  onNameChange={(name) => plan.updateOp(i, { name })}
                />
              ))}

              {plan.applyState.status === 'error' && (
                <ErrorAlert message={plan.applyState.message} />
              )}

              <button
                type="button"
                onClick={() => void plan.apply()}
                disabled={plan.applyState.status === 'applying' || plan.enabledCount === 0}
                className="inline-flex items-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-all duration-200 hover:-translate-y-0.5 disabled:opacity-40 disabled:hover:translate-y-0"
              >
                {plan.applyState.status === 'applying'
                  ? 'Создаём…'
                  : `Создать выбранное (${plan.enabledCount})`}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
