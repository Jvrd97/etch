'use client';
// [review:need-review] PHASE-01/52-text-to-category-plan
// summary: onboarding draft page — transcript textarea, generate button, read-only additive-only plan preview, error + Retry

import { useState } from 'react';
import { Sparkles, AlertTriangle } from 'lucide-react';
import LoadingSpinner from '@/components/LoadingSpinner';
import ErrorAlert from '@/components/ErrorAlert';
import {
  onboardingAPI,
  type OnboardingPlan,
  type PlanField,
  type PlanOperation,
} from '@/lib/api';

type State =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'done'; plan: OnboardingPlan };

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

function OperationCard({ op }: { op: PlanOperation }) {
  if (op.op === 'create_category') {
    return (
      <div className="bg-card border border-white/5 rounded-3xl px-6 py-5">
        <div className="flex items-center justify-between gap-3">
          <p className="text-base font-semibold text-text-primary">
            Новая категория: {op.name}
          </p>
          {op.name_conflict && (
            <span className="inline-flex items-center gap-1.5 text-xs text-danger">
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
      </div>
    );
  }
  return (
    <div className="bg-card border border-white/5 rounded-3xl px-6 py-5">
      <p className="text-base font-semibold text-text-primary">
        Новое поле в категории #{op.category_id}
      </p>
      <FieldList fields={[op.field]} />
    </div>
  );
}

export default function OnboardingPage() {
  const [transcript, setTranscript] = useState('');
  const [state, setState] = useState<State>({ status: 'idle' });

  const generate = async () => {
    const text = transcript.trim();
    if (!text) return;
    setState({ status: 'loading' });
    try {
      const plan = await onboardingAPI.draft(text);
      setState({ status: 'done', plan });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Не удалось построить план';
      setState({ status: 'error', message });
    }
  };

  return (
    <div className="space-y-8 animate-fade-rise">
      <div>
        <h1 className="text-4xl font-bold text-text-primary tracking-tight">
          Конструктор
          <span className="text-lime">.</span>
        </h1>
        <p className="mt-2 text-text-secondary">
          Опишите словами, что хотите отслеживать — получите план того, что будет
          создано. Ничего не сохраняется, это предпросмотр.
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
            state.plan.operations.map((op, i) => <OperationCard key={i} op={op} />)
          )}
        </div>
      )}
    </div>
  );
}
