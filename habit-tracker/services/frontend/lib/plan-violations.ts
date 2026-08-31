// [review:need-review] PHASE-03/147, PHASE-03/148
// summary: pure reading of the day's violations — which lines a rule was found on, the rule spelled in Russian, how much a violation costs, who assembled the plan that is on screen, and — when the skeleton assembled it — why the model did not

import type {
  Plan,
  PlanFallbackReason,
  PlanRuleCode,
  PlanViolation,
} from '@/lib/api';

/**
 * What each rule of the canon means, in the words the screen shows.
 *
 * The codes stay machine-readable and the Russian lives here, the same way
 * `mark.state` and `verdict.reason` are handled: an error a person can act on
 * has to say what to fix, and «правило free_evening_empty» does not.
 */
const RULE_LABELS: Record<PlanRuleCode, string> = {
  hard_edges_only: 'жёсткими бывают только края дня',
  free_evening_empty: 'свободный вечер не расписывается',
  work_cap: 'потолок рабочих минут',
  task_cap: 'потолок числа задач',
  health_before_work: 'здоровье раньше работы',
  relationship_anchor_required: 'вечер с близкими в нерабочий вечер',
  no_overlap: 'окна не пересекаются',
  target_day_only: 'строки пишутся только на этот день',
};

/** The rule in the words a person reads; the code itself when it is unknown. */
export function ruleLabel(code: PlanRuleCode | string): string {
  return RULE_LABELS[code as PlanRuleCode] ?? code;
}

/**
 * Which lines each rule was found on.
 *
 * Built by id, never by text: a violation carries no text at all, which is the
 * point — the row outlives the plan, and a task can be named after a diagnosis.
 * `detail.item_ids` is the only place ids live, and a violation that names none
 * (a missing anchor, a day off with no evening) is about the plan as a whole
 * and contributes nothing here.
 */
export function violationsByItem(
  violations: PlanViolation[]
): Map<string, PlanViolation[]> {
  const byItem = new Map<string, PlanViolation[]>();
  for (const violation of violations) {
    const ids = violation.detail?.item_ids;
    if (!Array.isArray(ids)) continue;
    for (const id of ids) {
      if (typeof id !== 'string') continue;
      byItem.set(id, [...(byItem.get(id) ?? []), violation]);
    }
  }
  return byItem;
}

/**
 * The violations that are about the day rather than about a line.
 *
 * A missing health anchor and a day off without the evening with the family
 * have nothing to attach to: the offending line is the one that is not there.
 * They are shown above the plan instead of being lost.
 */
export function planWideViolations(violations: PlanViolation[]): PlanViolation[] {
  return violations.filter((violation) => {
    const ids = violation.detail?.item_ids;
    return !Array.isArray(ids) || ids.length === 0;
  });
}

/**
 * Who assembled the plan on screen.
 *
 * Читается по `source`, а не по заголовку: заголовок человек переписывает, а
 * колонка остаётся. Без этой подписи «почему в плане именно это» — вопрос,
 * на который экран не отвечает.
 */
export function planAuthorLabel(plan: Pick<Plan, 'source'>): string {
  if (plan.source === 'llm') return 'Собран моделью и проверен каноном';
  if (plan.source === 'fallback') return 'Собран скелетом из канона';
  if (plan.source === 'manual') return 'Собран скелетом из канона';
  if (plan.source === 'import') return 'Перенесён из файлов';
  return 'Собран на /day-open';
}

/**
 * Почему план собрал скелет, а не модель, — человеческой фразой.
 *
 * Четыре кода, четыре разных ответа. «Не получилось» на все случаи было бы
 * подписью, после которой человек всё равно идёт в логи: кончившаяся подписка
 * и план, дважды нарушивший канон, чинятся по-разному.
 */
export const FALLBACK_REASON_LABELS: Record<PlanFallbackReason, string> = {
  llm_not_configured: 'модель не настроена',
  llm_error: 'модель не ответила',
  llm_timeout: 'модель не уложилась в бюджет',
  llm_plan_invalid: 'план модели дважды нарушил канон',
};

/**
 * Подпись «почему скелет», или null, когда план собран не запасным путём.
 *
 * Отдельной функцией, а не веткой внутри `planAuthorLabel`: авторство есть у
 * каждого плана, причина — только у части, и склеенная строка «Собран скелетом
 * (—)» была бы у трёх планов из четырёх.
 */
export function planFallbackLabel(
  plan: Pick<Plan, 'source' | 'fallback_reason'>
): string | null {
  if (plan.source !== 'fallback' || plan.fallback_reason === null) return null;
  return `Почему: ${FALLBACK_REASON_LABELS[plan.fallback_reason]}`;
}
