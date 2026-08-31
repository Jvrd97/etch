// [review:need-review] PHASE-03/114
// summary: the words of the retrieval line under a chat answer — the machine query name turned into Russian, the one-line summary «сон за 14 дней (14 строк, 620 знаков)», and the refusal spelled out instead of shown as a code

import type { ChatRetrieval } from '@/lib/api';
import { formatTokens } from '@/lib/chat-usage';

/**
 * Именованные выборки словами.
 *
 * Отдельный модуль, а не разметка внутри компонента, по той же причине, что и
 * `chat-context`: строка «что было запрошено» — это ответ на вопрос об
 * приватности, и он обязан проверяться тестом, а не читаться глазами в JSX.
 */

/**
 * Имена выборок по-русски.
 *
 * Ключи — машинные имена из `app/llm/chat/retrieval.py`. Незнакомое имя
 * показывается как есть: седьмое имя, добавленное на бэкенде, не должно
 * исчезать с экрана только потому, что его сюда не вписали, — экран аудита,
 * молчащий про новую выборку, хуже экрана с английским словом.
 */
export const QUERY_LABELS: Record<string, string> = {
  day_card: 'карточка дня',
  entries_range: 'записи трекера',
  journal_range: 'дневник',
  health_daily: 'здоровье по дням',
  streak: 'серия по категории',
  table_slice: 'свод таблицы',
};

export function queryLabel(name: string): string {
  return QUERY_LABELS[name] ?? name;
}

/** Что показывается вместо диапазона, когда выборка его не принимает. */
const NO_RANGE = '';

/**
 * Диапазон дат выборки одной подписью, либо пустая строка.
 *
 * Читается из параметров, а не из отдельного поля: параметры — то, что реально
 * ушло в запрос, и подпись, собранная из чего-то другого, врала бы ровно в том
 * месте, ради которого её и читают.
 */
export function rangeLabel(params: Record<string, unknown>): string {
  const from = params.date_from;
  const to = params.date_to;
  if (typeof from !== 'string' || typeof to !== 'string') {
    const single = params.date;
    return typeof single === 'string' ? `за ${single}` : NO_RANGE;
  }
  return from === to ? `за ${from}` : `${from} — ${to}`;
}

/**
 * Одна выборка строкой: что запрошено, за какой период и сколько отдано.
 *
 * Знаки названы вместе со строками намеренно: строк может быть четырнадцать, а
 * знаков — двадцать тысяч, и вопрос «сколько моих данных покинуло сервер»
 * отвечается вторым числом, а не первым.
 */
export function retrievalSummary(row: ChatRetrieval): string {
  const range = rangeLabel(row.params);
  const head = range ? `${queryLabel(row.query_name)} ${range}` : queryLabel(row.query_name);
  return `${head} (${formatTokens(row.row_count)} строк, ${formatTokens(row.chars)} знаков)`;
}

/** С чего начинается свёрнутая строка. */
export const RETRIEVALS_PREFIX = 'запрошено: ';

/**
 * Свёрнутая строка под ответом — что именно модель достала, без раскрытия.
 *
 * Перечисляет выборки, а не считает их: «запрошено: 2 выборки» отвечает на
 * вопрос «сколько», а спрашивают здесь «что». Раскрытие добавляет к этому
 * параметры, то есть точные границы запроса.
 */
export function retrievalsHeading(rows: ChatRetrieval[]): string {
  return RETRIEVALS_PREFIX + rows.map(retrievalSummary).join('; ');
}

/** Что показывается вместо счётчиков у выборки, которой сервер отказал. */
export const REFUSED_TEXT: Record<string, string> = {
  unknown_query: 'такого имени нет',
  bad_params: 'параметры за потолком',
};

/**
 * Строка про идущий ход: что модель полезла доставать прямо сейчас.
 *
 * Отдельно от `retrievalSummary`, потому что источник другой: у идущего хода
 * нет ни id строки, ни времени записи — есть имя и два счётчика, приехавшие
 * событием. Общий тип на два разных источника был бы типом с половиной
 * необязательных полей.
 */
export function liveRetrievalLine(row: {
  queryName: string;
  rowCount: number;
  chars: number;
  refusal: string | null;
}): string {
  const head = queryLabel(row.queryName);
  if (row.refusal !== null) {
    return `${head} — ${REFUSED_TEXT[row.refusal] ?? 'отказано'}`;
  }
  return `${head} (${formatTokens(row.rowCount)} строк, ${formatTokens(row.chars)} знаков)`;
}
