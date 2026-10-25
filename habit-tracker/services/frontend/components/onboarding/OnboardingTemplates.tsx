'use client';
// [review:need-review] PHASE-01/219-templates-in-onboarding
// summary: onboarding step that offers the built-in category templates through the shared TemplatePicker and tells the person what was added and what was skipped; both onboarding shells render it above the voice builder

import { useState } from 'react';
import TemplatePicker, { type TemplateClient } from '@/components/categories/TemplatePicker';
import type { CategoryTemplate, CategoryTemplateApplyResponse } from '@/lib/api';

type Step =
  | { status: 'open' }
  | { status: 'dismissed' }
  | { status: 'applied'; added: string[]; skipped: string[] };

interface OnboardingTemplatesProps {
  client?: TemplateClient;
  onOpenCategories: () => void;
}

const SECONDARY_BUTTON_CLASS =
  'inline-flex items-center justify-center px-5 py-3 bg-surface border border-white/10 text-text-primary rounded-3xl font-medium transition-colors duration-200 hover:border-lime/30';

/** `skipped` carries template keys; the catalog the picker showed turns them into names. */
function skippedNames(skipped: string[], templates: CategoryTemplate[]): string[] {
  return skipped.map((key) => templates.find((t) => t.key === key)?.name ?? key);
}

export default function OnboardingTemplates({ client, onOpenCategories }: OnboardingTemplatesProps) {
  const [step, setStep] = useState<Step>({ status: 'open' });

  const applied = (result: CategoryTemplateApplyResponse, templates: CategoryTemplate[]) =>
    setStep({
      status: 'applied',
      added: result.categories.map((c) => c.name),
      skipped: skippedNames(result.skipped, templates),
    });

  if (step.status === 'dismissed') {
    return (
      <button type="button" onClick={() => setStep({ status: 'open' })} className={SECONDARY_BUTTON_CLASS}>
        Показать шаблоны
      </button>
    );
  }

  if (step.status === 'applied') {
    return (
      <div
        role="status"
        className="bg-card border border-white/5 rounded-3xl p-6 space-y-3 text-text-primary"
      >
        {step.added.length > 0 && <p>Добавлено: {step.added.join(', ')}.</p>}
        {step.skipped.length > 0 && (
          <p className="text-text-secondary">
            Пропущено, такая категория уже есть: {step.skipped.join(', ')}. Она осталась как была.
          </p>
        )}
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={onOpenCategories} className={SECONDARY_BUTTON_CLASS}>
            Открыть категории
          </button>
          <button type="button" onClick={() => setStep({ status: 'open' })} className={SECONDARY_BUTTON_CLASS}>
            Показать шаблоны
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <TemplatePicker client={client} onApplied={applied} />
      <button type="button" onClick={() => setStep({ status: 'dismissed' })} className={SECONDARY_BUTTON_CLASS}>
        Пропустить шаблоны
      </button>
    </div>
  );
}
