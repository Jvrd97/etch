// [review:need-review] PHASE-03/139
// summary: the words of the rules screen — the dry run said in one sentence that distinguishes «нечего было прогонять» from «правило не ловит», the rule a match is taken from named by its pattern rather than by its id, and the before/after of a re-markup read as a movement of shares

import type { Role, RoleReclassified, RoleRule, RoleRuleDryRun } from '@/lib/api';

/**
 * Экран правил разметки словами.
 *
 * Отдельный модуль, потому что все три предложения здесь несущие. «Нечего было
 * прогонять» против «правило не ловит» — разные ответы, и человек, прочитавший
 * второй вместо первого, идёт переписывать работающее правило. «Отобрано у
 * такого-то» без имени правила — это id в интерфейсе. И «изменилось всё, кроме
 * ваших правок» без числа защищённых записей неотличимо от «их не было».
 */

export const DRY_RUN_LABEL = 'Прогнать по истории';
export const SAVE_LABEL = 'Сохранить правило';
export const RECLASSIFY_LABEL = 'Переразметить';

/** Источники разметки — те же коды, что в `app/models/role.py`. */
export const SOURCE_OPTIONS: { id: string; label: string }[] = [
  { id: 'app_usage', label: 'Окна приложений' },
  { id: 'git', label: 'Коммиты' },
  { id: 'clickup', label: 'ClickUp' },
  { id: 'plan', label: 'План дня' },
  { id: 'manual', label: 'Ручной ввод' },
];

/** По чему правило сверяет образец. Коды — из `MATCHER_KINDS`. */
export const MATCHER_OPTIONS: { id: string; label: string }[] = [
  { id: 'commit_prefix', label: 'Начало сообщения коммита' },
  { id: 'window_title_regex', label: 'Заголовок окна (регулярка)' },
  { id: 'bundle_id', label: 'Bundle id приложения' },
  { id: 'repo_path_glob', label: 'Путь репозитория (glob)' },
  { id: 'clickup_list', label: 'Список ClickUp' },
  { id: 'clickup_tag', label: 'Тег ClickUp' },
  { id: 'plan_section', label: 'Секция плана' },
];

/** Что печатается, когда прогонять было нечего. */
export const NOTHING_TO_SCAN =
  'За этот период размеченных строк нет — прогонять пока не по чему.';

/**
 * Итог прогона одной фразой.
 *
 * Пустая история названа отдельно и первой: ноль совпадений из нуля строк и
 * ноль совпадений из трёхсот — разные ответы, и только второй значит «правило
 * не ловит».
 */
export function dryRunSummary(run: RoleRuleDryRun): string {
  if (run.scanned_rows === 0) return NOTHING_TO_SCAN;
  return (
    `Зацепило интервалов: ${run.matched_time_blocks}, актов: ${run.matched_acts} ` +
    `из ${run.scanned_rows} строк за ${run.date_from} — ${run.date_to}.`
  );
}

/**
 * У каких правил новое отбирает совпадения — по образцу, а не по id.
 *
 * Это и есть то, ради чего человек смотрит на прогон: правило, ловящее сто
 * строк, из которых девяносто уже размечены верно, разметку не улучшает, а
 * перекрашивает.
 */
export function takenFromLines(run: RoleRuleDryRun, rules: RoleRule[]): string[] {
  const byId = new Map(rules.map((one) => [String(one.id), one]));
  const lines = Object.entries(run.taken_from).map(([id, count]) => {
    const rule = byId.get(id);
    const name = rule === undefined ? `правило ${id}` : `«${rule.pattern}»`;
    return `Отбирает у ${name}: ${count}`;
  });
  if (run.taken_from_nobody > 0) {
    lines.push(`Ничьих совпадений: ${run.taken_from_nobody}`);
  }
  return lines;
}

/** Записи, подтверждённые человеком, — их не трогали, и это сказано числом. */
export function protectedLine(result: RoleReclassified): string {
  return (
    `Пересчитано строк: ${result.scanned_rows}, изменено интервалов: ` +
    `${result.changed_time_blocks}, актов: ${result.changed_acts}. ` +
    `Подтверждённых вами записей не тронуто: ${result.protected}.`
  );
}

/**
 * Доли до и после, по строке на роль, которая сдвинулась.
 *
 * Роли, у которых ничего не изменилось, в список не попадают: смысл отчёта —
 * показать движение, и строка «25% → 25%» его прячет за собой.
 */
export function reclassifyLines(
  result: RoleReclassified,
  roles: Role[]
): string[] {
  const titles = new Map(roles.map((one) => [one.id, one.title]));
  const after = new Map(result.after.map((one) => [one.role_id, one.share_pct]));
  const before = new Map(result.before.map((one) => [one.role_id, one.share_pct]));
  const ids = [...new Set([...before.keys(), ...after.keys()])];
  return ids
    .filter((id) => (before.get(id) ?? 0) !== (after.get(id) ?? 0))
    .map((id) => {
      const title = titles.get(id) ?? `роль ${id}`;
      return `${title}: ${before.get(id) ?? 0}% → ${after.get(id) ?? 0}%`;
    });
}

/** Месяц, кончающийся названным днём: границы переразметки по умолчанию. */
export function defaultRange(lastDay: string): { from: string; to: string } {
  const end = new Date(`${lastDay}T00:00:00Z`);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - 29);
  return { from: start.toISOString().slice(0, 10), to: lastDay };
}
