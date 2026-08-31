// [review:need-review] PHASE-03/87, PHASE-03/88, PHASE-03/110
// summary: pure reading of a plan — the window label built from the one clock reading in lib/time, which schedule lines collide, the kinds of every item by id, the plain-Russian names of section kinds and item rigidity, and the warnings of an edit indexed by the code of the line they name

import type {
  Plan,
  PlanItem,
  PlanItemKind,
  PlanRigidity,
  PlanSection,
  PlanWarning,
  ScheduleOverlap,
} from '@/lib/api';
import { formatMinutes } from '@/lib/day-format';
import { clock, clockRange } from '@/lib/time';

/** Shown where a plan would be. A day without one is an answer, not an error. */
export const EMPTY_PLAN_TEXT = 'В плане нет ни одной секции';

/** Said above a schedule with nothing in it: no line claimed a piece of the clock. */
export const EMPTY_SCHEDULE_TEXT = 'Ни у одного пункта нет окна';

/** Said next to a pair of windows that collide. */
export const OVERLAP_BADGE = 'наложение';

/**
 * `09:30-11:00` — the shape the window had when plans were files.
 *
 * The clock itself is read by `lib/time`: which *day* a moment belongs to was
 * decided by the server, and what the wall in front of the reader says is one
 * answer for the whole front end.
 */
export function formatWindow(startsAt: string, endsAt: string | null): string {
  // Точка печатается одним временем, а не «06:00-06:00»: повтор читается как
  // окно нулевой длины, а это момент.
  if (endsAt === null) return clock(startsAt);
  return clockRange(startsAt, endsAt);
}

/**
 * Что стоит в колонке длительности у точки.
 *
 * Прочерк, а не «0 мин»: ноль — это длительность, а у момента её нет. Так же
 * читается «20:00 — Конец» в шаблоне плана, откуда эти строки и пришли.
 */
export const POINT_DURATION = '—';

/** Длительность строки расписания, как её читает человек. */
export function scheduleDuration(minutes: number | null): string {
  return minutes === null ? POINT_DURATION : formatMinutes(minutes);
}

/**
 * The ids of every schedule line involved in at least one collision.
 *
 * A set rather than a search per row: the schedule is rendered once and a
 * lookup per line keeps the highlight O(n) instead of O(n²) — and, more to the
 * point, keeps the answer identical for both halves of a pair.
 */
export function overlappingItemIds(overlaps: ScheduleOverlap[]): Set<string> {
  const ids = new Set<string>();
  for (const overlap of overlaps) {
    ids.add(overlap.left_item_id);
    ids.add(overlap.right_item_id);
  }
  return ids;
}

/** How much of the day two colliding windows claim twice over. */
export function totalOverlapMinutes(overlaps: ScheduleOverlap[]): number {
  return overlaps.reduce((sum, overlap) => sum + overlap.overlap_minutes, 0);
}

const SECTION_TITLES: Record<string, string> = {
  anchors: 'Якоря',
  training: 'Тренировка',
  hard_points: 'Жёсткие точки дня',
  work: 'Работа',
  study: 'Учёба',
  evening: 'Вечер',
  personal: 'Личное',
  queue: 'Очередь',
  free: 'Свободный блок',
  other: 'Ещё',
};

/**
 * What to call a section on screen.
 *
 * The plan's own title wins: `kind` is a machine's grouping and the author's
 * heading is what the day was actually written with. The fallback exists only
 * for a section that arrived without one.
 */
export function sectionTitle(section: PlanSection): string {
  if (section.title !== null && section.title.trim() !== '') return section.title;
  return SECTION_TITLES[section.kind] ?? SECTION_TITLES.other;
}

const RIGIDITY_LABELS: Record<PlanRigidity, string> = {
  hard: 'жёстко',
  soft: 'двигается',
  free: 'свободно',
};

/** Plain-Russian rigidity; only `hard` and `free` are worth showing. */
export function rigidityLabel(rigidity: PlanRigidity): string | null {
  if (rigidity === 'soft') return null;
  return RIGIDITY_LABELS[rigidity];
}

const KIND_LABELS: Partial<Record<PlanItemKind, string>> = {
  task: 'задача',
  anchor: 'якорь',
  hard_point: 'жёсткая точка',
  minimum: 'минимум',
};

/** The badge next to a line, for the kinds where it carries meaning. */
export function itemKindLabel(kind: PlanItemKind): string | null {
  return KIND_LABELS[kind] ?? null;
}

/**
 * Every item of a plan by id, with the kind it is.
 *
 * The map, not a count: the header counts tasks against marks, and the marks
 * are keyed by item id. Building it once per plan keeps the counting in the day
 * screen from walking the tree again on every click.
 */
export function itemKindsById(plan: Plan | null): Map<string, PlanItemKind> {
  const kinds = new Map<string, PlanItemKind>();
  const walk = (items: PlanItem[]): void => {
    for (const item of items) {
      kinds.set(item.id, item.kind);
      walk(item.children);
    }
  };
  if (plan !== null) for (const section of plan.sections) walk(section.items);
  return kinds;
}

/**
 * The labels an item carries that have no column of their own.
 *
 * Read back out of `extra` so that `Формат :: аудио` is visible on screen and
 * not merely preserved in a database nobody opens.
 */
export function extraLines(item: PlanItem): { label: string; value: string }[] {
  return Object.entries(item.extra).map(([label, value]) => ({
    label,
    value: typeof value === 'string' ? value : JSON.stringify(value),
  }));
}

/**
 * The warnings of an edit, indexed by the code of the line that earned them.
 *
 * Indexed by code and not by id because that is what the server names: a
 * rejection of `#87` and a warning of `#110` are the same rule with the same
 * address, and the screen that draws the second must not invent a second way to
 * find the line. A warning about a line without a code stays out of the map —
 * it is shown above the plan, where it can still be read.
 */
export function warningsByCode(warnings: PlanWarning[]): Map<string, string> {
  const byCode = new Map<string, string>();
  for (const warning of warnings) {
    if (warning.item_code !== null) byCode.set(warning.item_code, warning.message);
  }
  return byCode;
}
