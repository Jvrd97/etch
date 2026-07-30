'use client';
// [review:need-review] PHASE-01/62-mobile-onboarding-twin
// summary: mobile voice-category-builder — same useOnboardingPlan flow as the desktop page, laid out for a 375pt screen: one card per operation with every control stacked on its own 44pt row

import { useRouter } from 'next/navigation';
import { AlertTriangle, Sparkles } from 'lucide-react';
import ErrorAlert from '@/components/ErrorAlert';
import LoadingSpinner from '@/components/LoadingSpinner';
import { useOnboardingPlan, type OpState } from '@/hooks/useOnboardingPlan';
import type { PlanField, PlanOperation } from '@/lib/api';
import { MOBILE_PATH_PREFIX } from '@/lib/routes';
import { TAP_TARGET_PX, entryInputClass } from '@/lib/ui-constants';

const PRIMARY_BUTTON_CLASS =
  'w-full inline-flex items-center justify-center gap-2 px-6 py-3 bg-lime text-background rounded-3xl font-medium transition-transform duration-200 active:scale-95 disabled:opacity-40 disabled:active:scale-100';

const SECONDARY_BUTTON_CLASS =
  'w-full inline-flex items-center justify-center px-5 py-3 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-transform duration-200 active:scale-95';

/** The fields an operation would create, one per line. */
function FieldList({ fields }: { fields: PlanField[] }) {
  if (fields.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1">
      {fields.map((field, i) => (
        <li key={i} className="text-[13px] text-text-secondary break-words">
          {field.name}
          <span className="text-text-disabled"> · {field.field_type}</span>
          {field.is_required && <span className="text-text-disabled"> · required</span>}
        </li>
      ))}
    </ul>
  );
}

interface OperationCardProps {
  op: PlanOperation;
  state: OpState;
  position: number;
  onToggle: (enabled: boolean) => void;
  onNameChange: (name: string) => void;
}

/**
 * One planned operation as a card.
 *
 * The desktop preview puts the checkbox, the name input, the mode line and the
 * conflict badge in a single row; at 375pt that row either wraps into mush or
 * pushes the page sideways. Here each of them is its own full-width block, in
 * the same order.
 */
function OperationCard({ op, state, position, onToggle, onNameChange }: OperationCardProps) {
  const isCreate = op.op === 'create_category';
  const title = isCreate ? op.name : op.field.name;

  return (
    <div className="bg-card border border-white/5 rounded-3xl p-4 space-y-3">
      <label
        style={{ minHeight: TAP_TARGET_PX }}
        className="flex items-center gap-3 cursor-pointer"
      >
        <input
          type="checkbox"
          checked={state.enabled}
          onChange={(e) => onToggle(e.target.checked)}
          aria-label={
            isCreate ? `Создать категорию ${op.name}` : `Добавить поле ${op.field.name}`
          }
          className="w-5 h-5 accent-lime rounded shrink-0"
        />
        <span className="min-w-0 text-sm font-medium text-text-secondary truncate">
          {isCreate ? 'Новая категория' : `Поле в категории #${op.category_id}`}
        </span>
      </label>

      {isCreate ? (
        <>
          <input
            type="text"
            value={state.name}
            onChange={(e) => onNameChange(e.target.value)}
            aria-label={`Имя категории ${op.name}`}
            style={{ minHeight: TAP_TARGET_PX }}
            className={entryInputClass}
          />
          {op.name_conflict && (
            <p className="flex items-center gap-1.5 text-[13px] text-danger">
              <AlertTriangle className="w-4 h-4 shrink-0" strokeWidth={2} />
              имя уже занято
            </p>
          )}
          <p className="text-[13px] text-text-disabled break-words">
            {op.display_mode} · {op.streak_mode}
            {op.group ? ` · ${op.group}` : ''}
          </p>
          <FieldList fields={op.fields} />
        </>
      ) : (
        <>
          {/* Position, not the name: two ops can add fields with the same name
              to different categories, and the heading is the only thing telling
              the two cards apart on a screen this narrow. */}
          <p className="text-base font-semibold text-text-primary break-words">
            {position}. {title}
          </p>
          <FieldList fields={[op.field]} />
        </>
      )}
    </div>
  );
}

export default function MobileOnboardingPage() {
  const router = useRouter();
  const plan = useOnboardingPlan({
    onApplied: () => router.push(`${MOBILE_PATH_PREFIX}/categories`),
  });
  const generate = () => void plan.generate();

  return (
    <div className="space-y-4 animate-fade-rise">
      <p className="text-sm text-text-secondary">
        Опишите словами, что хотите отслеживать — получите план и создайте выбранное одним
        нажатием.
      </p>

      <textarea
        value={plan.transcript}
        onChange={(e) => plan.setTranscript(e.target.value)}
        rows={5}
        aria-label="Что отслеживать"
        placeholder="Например: хочу трекать сон — сколько часов и качество"
        className={`${entryInputClass} resize-y`}
      />

      <button
        type="button"
        onClick={generate}
        disabled={!plan.canGenerate}
        style={{ minHeight: TAP_TARGET_PX }}
        className={PRIMARY_BUTTON_CLASS}
      >
        <Sparkles className="w-4 h-4" strokeWidth={2} />
        Сгенерировать план
      </button>

      {plan.draft.status === 'loading' && <LoadingSpinner size="lg" />}

      {plan.draft.status === 'error' && (
        <div className="space-y-3">
          <ErrorAlert message={plan.draft.message} />
          <button
            type="button"
            onClick={generate}
            style={{ minHeight: TAP_TARGET_PX }}
            className={SECONDARY_BUTTON_CLASS}
          >
            Retry
          </button>
        </div>
      )}

      {plan.draft.status === 'done' &&
        (plan.draft.plan.operations.length === 0 ? (
          <p className="text-sm text-text-secondary">
            Модель не предложила изменений. Попробуйте описать подробнее.
          </p>
        ) : (
          <div className="space-y-3">
            {plan.draft.plan.operations.map((op, i) => (
              <OperationCard
                // Index-keyed: a plan operation has no id, and the list is
                // replaced wholesale by the next draft rather than reordered.
                key={i}
                op={op}
                state={plan.opStates[i]}
                position={i + 1}
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
              style={{ minHeight: TAP_TARGET_PX }}
              className={PRIMARY_BUTTON_CLASS}
            >
              {plan.applyState.status === 'applying'
                ? 'Создаём…'
                : `Создать выбранное (${plan.enabledCount})`}
            </button>
          </div>
        ))}
    </div>
  );
}
