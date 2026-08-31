// [review:need-review] PHASE-03/138
// summary: the words of the role summary and the copy of the Friday report block — the target share always labelled a hypothesis, the gap from it read with a sign, the `unassigned` line named as a signal rather than as «прочее», and one clipboard write that says whether it landed

import type { RoleSummary, RoleSummarySlice } from '@/lib/api';

/**
 * Сводка ролей словами.
 *
 * Отдельный модуль, а не разметка внутри компонента: подпись «гипотеза» и
 * порог `unassigned` — утверждения, за которые тикет и брался, и проверяться
 * они должны тестом, а не чтением JSX.
 *
 * Текста самого отчёта здесь нет и не будет: его рендерит сервер, и вторая
 * реализация форматирования разошлась бы с первой на первой же правке целевых
 * долей — молча.
 */

/** Заголовок блока сводки. */
export const SUMMARY_TITLE = 'Роли за период';

/** Что показывается вместо таблицы, когда за период нет ни минуты. */
export const EMPTY_SUMMARY = 'Записей за период нет.';

/**
 * Подпись целевых долей.
 *
 * Экран, называющий целевую долю нормой, врёт про её природу: она меняется от
 * квартала к кварталу и лежит полем в `role`, а день по ней не судится.
 */
export const TARGET_HYPOTHESIS = 'целевая доля — гипотеза квартала, а не норма';

/** Как называется строка неотнесённой работы. */
export const UNASSIGNED_TITLE = 'Не отнесено';

/** Заголовок блока готового текста отчёта. */
export const REPORT_TITLE = 'Пятничный отчёт';

/** Надпись на кнопке, и что она говорит после нажатия. */
export const COPY_LABEL = 'Скопировать';
export const COPY_DONE = 'Скопировано';
export const COPY_FAILED = 'Буфер обмена недоступен';

/** Минуты часами и минутами — тем же видом, что и везде на экранах дня. */
export function summaryMinutes(minutes: number): string {
  return `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`;
}

/**
 * Отклонение от целевой доли со знаком, либо `null` — цели нет.
 *
 * Знак обязателен: «5 п.п.» не отвечает на вопрос, в какую сторону разошлось,
 * а весь смысл строки в этом.
 */
export function deltaText(slice: RoleSummarySlice): string | null {
  if (slice.delta_pct === null) return null;
  const sign = slice.delta_pct > 0 ? '+' : '';
  return `${sign}${slice.delta_pct} п.п.`;
}

/** Целевая доля роли, либо прочерк. */
export function targetText(slice: RoleSummarySlice): string {
  return slice.target_share_pct === null ? '—' : `${slice.target_share_pct}%`;
}

/**
 * Фраза про `unassigned`, и она же — сигнал.
 *
 * Порог называет сервер (`lag_threshold_pct`): второе число на экране разошлось
 * бы с ADR ровно тогда, когда порог решат подвинуть.
 */
export function unassignedNote(summary: RoleSummary): string {
  if (!summary.rules_lag) {
    return (
      `не отнесено ${summary.unassigned_share_pct}% минут периода; ` +
      `за скользящие 30 дней — ${summary.window_unassigned_share_pct}% ` +
      `при пороге ${summary.lag_threshold_pct}%`
    );
  }
  return (
    `правила разметки отстали: за скользящие 30 дней не отнесено ` +
    `${summary.window_unassigned_share_pct}% минут при пороге ` +
    `${summary.lag_threshold_pct}%. По ADR-0020 автоматику пора выключать ` +
    `в пользу ручного ввода — чинить правила полдня в неделю дороже`
  );
}

/** Роли периода без строки «не отнесено»: она идёт своей, наравне, но своей. */
export function workingRoles(summary: RoleSummary): RoleSummarySlice[] {
  return summary.roles.filter((one) => one.role_code !== 'unassigned');
}

/** Акты роли по видам одной строкой; пустая строка — актов не было. */
export function actsText(slice: RoleSummarySlice): string {
  const kinds = Object.entries(slice.act_counts).sort(([a], [b]) => a.localeCompare(b));
  if (kinds.length === 0) return '';
  return kinds.map(([kind, count]) => `${kind} × ${count}`).join(', ');
}

/**
 * Положить готовый блок в буфер обмена; `false` — не получилось.
 *
 * Отказ возвращается значением, а не исключением: буфера может не быть вовсе
 * (страница открыта не по https, браузер запретил), и это не поломка экрана —
 * это «скопируйте руками», и сказать об этом должен сам экран.
 */
export async function copyReport(markdown: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(markdown);
    return true;
  } catch {
    return false;
  }
}

/** Периоды, за которые сводку смотрят с экрана ролей. */
export type PeriodChoice = 'week' | 'month' | 'quarter';

/** Сколько дней назад смотрит каждый из них, считая сегодняшний. */
const PERIOD_DAYS: Record<PeriodChoice, number> = {
  week: 7,
  month: 30,
  quarter: 90,
};

export const PERIOD_OPTIONS: { id: PeriodChoice; label: string }[] = [
  { id: 'week', label: 'Неделя' },
  { id: 'month', label: 'Месяц' },
  { id: 'quarter', label: 'Квартал' },
];

/**
 * Границы периода, кончающегося названным днём.
 *
 * Считается от дня, который назвал сервер, а не от календаря браузера: сутки
 * начинаются в 4:00, и в 00:30 «сегодня» у браузера и у приложения разные.
 */
export function periodBack(
  lastDay: string,
  period: PeriodChoice
): { from: string; to: string } {
  const end = new Date(`${lastDay}T00:00:00Z`);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - (PERIOD_DAYS[period] - 1));
  return { from: start.toISOString().slice(0, 10), to: lastDay };
}
