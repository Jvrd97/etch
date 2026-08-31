// [review:need-review] PHASE-03/113
// summary: the words of the "что чат видит" disclosure — machine section names turned into Russian, and the one line that says how big the day card was and what the ceiling ate

import type { ChatContext } from '@/lib/api';
import { formatTokens } from '@/lib/chat-usage';

/**
 * Карточка дня словами.
 *
 * Отдельный модуль, а не разметка внутри компонента: «какая секция выпала» —
 * единственный вопрос, который вызывает пометка об обрезке, и ответ на него
 * должен быть проверяем тестом, а не прочитан глазами в JSX.
 */

/**
 * Имена секций карточки по-русски.
 *
 * Ключи — машинные имена из `app/llm/chat/context.py`. Незнакомое имя
 * показывается как есть: новая секция на бэкенде не должна исчезать с экрана
 * только потому, что её сюда не вписали.
 */
export const SECTION_LABELS: Record<string, string> = {
  plan: 'план дня и отметки',
  health: 'здоровье за день',
  entries: 'записи трекера',
  journal: 'дневник',
};

export function sectionLabel(name: string): string {
  return SECTION_LABELS[name] ?? name;
}

/**
 * Размер карточки одной строкой: сколько знаков ушло в промпт из скольких можно.
 *
 * Разряды группирует `formatTokens` — там это «число с пробелами по три
 * разряда», и второй такой же форматтер разошёлся бы с ним на первом же
 * исправлении.
 */
export function sizeSummary(context: ChatContext): string {
  return `${formatTokens(context.chars)} из ${formatTokens(context.max_chars)} знаков`;
}

/**
 * Пометка об обрезке или `null`, когда карточка поместилась целиком.
 *
 * Секции названы поимённо: «обрезано» без имён оставляет читателя гадать, чего
 * именно модель не увидела, — а он открыл раскрывашку именно за этим.
 */
export function truncationNote(context: ChatContext): string | null {
  if (!context.truncated) return null;
  if (context.dropped_sections.length === 0) {
    return 'Обрезано по потолку.';
  }
  const names = context.dropped_sections.map(sectionLabel).join(', ');
  return `Обрезано по потолку, строки потеряли: ${names}.`;
}
