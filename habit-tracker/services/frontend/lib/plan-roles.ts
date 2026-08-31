// [review:need-review] PHASE-03/140
// summary: pure labels for the plan's role markup — «архитектор · решение по модели данных» printed on a line that carries an intent to act, the line of the plan an act on `/roles` opens up to, and the two picker vocabularies (роль и вид акта) with «без роли» as the first option

import type { PlanItem, Role, RoleAct } from '@/lib/api';
import { actKindLabel } from '@/lib/role-format';

/** What the empty option of both pickers says, and the value it carries. */
export const NO_ROLE_LABEL = 'без роли';
export const NO_ACT_KIND_LABEL = 'без акта';
export const NO_VALUE = '';

/** Labels of the two fields the item form gains. */
export const ROLE_FIELD_LABEL = 'Роль';
export const ACT_KIND_FIELD_LABEL = 'Вид акта';

/** Label of the section field: whose minutes the windows under it are. */
export const SECTION_ROLE_LABEL = 'Роль секции';

/** Prefix of the line under an act that came from a plan. */
export const FROM_PLAN_PREFIX = 'из плана';

/**
 * The intent an item carries, as the line prints it, or null when it carries
 * none.
 *
 * Both halves are required. A vid without a role has nobody to charge the act
 * to, and a role without a kind is markup of minutes the section already does —
 * so an item holding one of the two says nothing rather than half a sentence.
 *
 * A role missing from the directory prints its id rather than disappearing: the
 * column is `SET NULL` on delete, so a row pointing at an unknown role means the
 * directory is being read stale, and a silently blank line would hide that.
 */
export function actIntentLine(item: PlanItem, roles: Role[]): string | null {
  if (item.role_id === null || item.act_kind === null) return null;
  const role = roles.find((candidate) => candidate.id === item.role_id);
  return `${role ? role.title : `роль ${item.role_id}`} · ${actKindLabel(item.act_kind)}`;
}

/**
 * The line of the plan an act came from, or null for an act typed by hand.
 *
 * The text arrives from the server rather than being looked up in the plan the
 * screen happens to hold: `/roles` and `/m/roles` do not load a plan, and an act
 * that could only be explained on the day screen would be explained nowhere.
 */
export function fromPlanLine(act: RoleAct): string | null {
  if (act.plan_item_text === null) return null;
  return `${FROM_PLAN_PREFIX}: ${act.plan_item_text}`;
}

/**
 * The value a `<select>` shows for a nullable id.
 *
 * `null` and `0` are different answers — «роль не выбрана» and «роль с id 0» —
 * and an empty string is the only value a select can hold that is neither.
 */
export function selectValue(id: number | null): string {
  return id === null ? NO_VALUE : String(id);
}

/** The id a `<select>` change means; empty is «убрать», not «оставить». */
export function selectedId(value: string): number | null {
  return value === NO_VALUE ? null : Number(value);
}

/** The kind a `<select>` change means; empty is «убрать». */
export function selectedKind(value: string): string | null {
  return value === NO_VALUE ? null : value;
}
