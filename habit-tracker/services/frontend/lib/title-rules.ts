// [review:need-review] PHASE-03/158
// summary: pure labels of the title-privacy screen — the two vocabularies (по чему совпадать, что делать с заголовком) in Russian, the sentence that says the order is meaning, the warning attached to the kill switch, and the count of what a rule actually did over a week

import type { TitleRule } from '@/lib/api';
import { countable } from '@/lib/plural';

/** What the order means, said where the order is drawn. */
export const ORDER_HINT =
  'Порядок — это смысл: выигрывает первое совпавшее правило, стрелки его меняют.';

/** Shown where the policy has no rules at all. */
export const EMPTY_POLICY_TEXT =
  'Правил нет: заголовки не сохраняются ни у одного приложения — политика по умолчанию запрещающая.';

/** Label of the switch that stops title collection entirely. */
export const KILL_SWITCH_LABEL = 'Собирать заголовки окон';

/**
 * What the kill switch does not do, printed next to it.
 *
 * Не украшение: рубильник, который выглядит как «стереть всё», однажды будет
 * нажат вместо чистки, и человек будет думать, что заголовков на сервере нет.
 */
export const KILL_SWITCH_WARNING =
  'Выключение останавливает новые заголовки. Те, что уже уехали на сервер, остаются — чистить их надо отдельно, руками.';

export const ADD_RULE_LABEL = 'Добавить правило';
export const UP_LABEL = 'Выше';
export const DOWN_LABEL = 'Ниже';

const MATCH_KIND_LABELS: Record<TitleRule['match_kind'], string> = {
  bundle_id: 'приложение',
  bundle_prefix: 'приложения с началом',
  title_regex: 'заголовок по regex',
};

const ACTION_LABELS: Record<TitleRule['action'], string> = {
  keep: 'оставить целиком',
  mask: 'оставить домен или расширение',
  drop: 'не сохранять',
};

/** Every kind the form offers, in the order it offers them. */
export const MATCH_KIND_OPTIONS: readonly {
  value: TitleRule['match_kind'];
  label: string;
}[] = (Object.keys(MATCH_KIND_LABELS) as TitleRule['match_kind'][]).map((value) => ({
  value,
  label: MATCH_KIND_LABELS[value],
}));

/** Every action the form offers, strictest last so `drop` is not the default choice. */
export const ACTION_OPTIONS: readonly {
  value: TitleRule['action'];
  label: string;
}[] = (Object.keys(ACTION_LABELS) as TitleRule['action'][]).map((value) => ({
  value,
  label: ACTION_LABELS[value],
}));

/** Human name of a match kind, falling back to the code. */
export function matchKindLabel(kind: TitleRule['match_kind']): string {
  return MATCH_KIND_LABELS[kind] ?? kind;
}

/** Human name of an action, falling back to the code. */
export function actionLabel(action: TitleRule['action']): string {
  return ACTION_LABELS[action] ?? action;
}

/**
 * What a rule actually did over the last week.
 *
 * A zero is the point of the line: a rule that never fired because of a typo in
 * its pattern looks exactly like a working one until somebody counts.
 */
export function hitsLine(rule: TitleRule): string {
  return `за 7 дней: ${countable(rule.hits_7d, 'срабатывание', 'срабатывания', 'срабатываний')}`;
}
