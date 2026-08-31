// [review:need-review] PHASE-03/150
// summary: чтение дифа плана на язык экрана — подпись «AI предлагал 09:00-11:00» под тронутым пунктом и сводка «человек переставил N пунктов» над планом, обе из одних и тех же строк журнала

import type { PlanAuthor, PlanDiff, PlanItemDiff } from '@/lib/api';
import { countable } from '@/lib/plural';

/** Кто предложил план — словом, а не кодом. */
const AUTHOR_LABEL: Record<PlanAuthor, string> = {
  ai: 'AI',
  fallback: 'скелет',
  human: 'человек',
  skill: 'скилл',
};

export function authorLabel(author: PlanAuthor): string {
  return AUTHOR_LABEL[author];
}

/**
 * Подпись под пунктом: что предлагала машина до того, как его тронули.
 *
 * Берётся первое записанное значение по каждому полю, а не последнее: человек
 * мог поправить окно трижды, и интересно то, с чего он начал, — предложение.
 * Окно склеивается обратно в «09:00-11:00», потому что читают его так, а два
 * конца порознь — форма хранения, а не форма чтения.
 */
export function proposalLine(item: PlanItemDiff, author: PlanAuthor | null): string | null {
  const first = new Map<string, string | null>();
  for (const change of item.changes) {
    if (!first.has(change.field)) first.set(change.field, change.old_value);
  }
  const who = author === null ? 'Машина' : authorLabel(author);
  const start = first.get('window_start');
  const end = first.get('window_end');
  if (start !== undefined || end !== undefined) {
    const from = start ?? '…';
    const to = end ?? '…';
    return `${who} предлагал ${from}-${to}`;
  }
  const text = first.get('text');
  if (text !== undefined && text !== null) return `${who} предлагал: ${text}`;
  if (first.has('status')) return `${who} этого пункта не предлагал`;
  if (first.has('ord') || first.has('section_id')) return `${who} ставил его на другое место`;
  return null;
}

/** Подписи по id пункта — то, что `PlanSections` принимает пропом `proposals`. */
export function proposalsOf(diff: PlanDiff | null): Map<string, string> {
  const lines = new Map<string, string>();
  if (diff === null) return lines;
  for (const item of diff.items) {
    const line = proposalLine(item, diff.revision_zero_author);
    if (line !== null) lines.set(item.plan_item_id, line);
  }
  return lines;
}

/**
 * Сводка над планом, или null, когда говорить нечего.
 *
 * «Плана никто не генерировал» и «человек ничего не менял» — разные вещи, и
 * обе молчат: в первом случае сравнивать не с чем, во втором сравнение сошлось.
 */
export function diffSummary(diff: PlanDiff | null): string | null {
  if (diff === null || diff.revision_zero === null || diff.moved_items === 0) return null;
  const items = countable(diff.moved_items, 'пункт', 'пункта', 'пунктов');
  return `Человек переставил ${items} из того, что предложил ${authorLabel(
    diff.revision_zero_author ?? 'ai'
  )}`;
}
