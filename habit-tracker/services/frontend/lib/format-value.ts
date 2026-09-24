// [review:need-review] #176
// summary: shared optional-unit formatting and field-specific quick-step fallback

export const DEFAULT_QUICK_STEPS = [-5, -1, 1, 5] as const;

export function formatValue(value: string | number, unit: string | null | undefined): string {
  return unit ? `${value} ${unit}` : String(value);
}

export function quickStepsForField(steps: number[] | null | undefined): readonly number[] {
  return steps ?? DEFAULT_QUICK_STEPS;
}

export function formatStep(step: number, unit: string | null | undefined): string {
  return formatValue(`${step > 0 ? '+' : ''}${step}`, unit);
}
