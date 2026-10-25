// [review:need-review] PHASE-03/105
// summary: what the sources screen says about one source — the three states told apart («не подключён», «нужен вход», «сломалось»), the next step for each error class, and the moment of a run written so that the day is never missing

import type { SignalSource } from '@/lib/api';

/**
 * Состояние источника, которое экран обязан показать словами.
 *
 * Размеченное объединение, а не три флага: «не подключён» (заготовка, читать
 * нечем), «нужен вход» (читать есть чем, но нет ключа или сессии) и «сломалось»
 * (был вход, и провайдер отказал) требуют разных действий. Заготовку, принятую
 * за сломанный источник, идут чинить — а чинить там нечего.
 */
export type SourceState = 'not_connected' | 'needs_login' | 'broken';

export const STATE_LABEL: Record<SourceState, string> = {
  not_connected: 'не подключён',
  needs_login: 'нужен вход',
  broken: 'сломалось',
};

/** Следующий шаг по классу отказа — тому, что присылает сервер. */
export const CLASS_HINT: Record<string, string> = {
  needs_login: 'Нужен вход: нет ключа или файла сессии. Введите ключ выше или войдите заново.',
  auth_expired: 'Провайдер отозвал доступ или он истёк: введите ключ заново.',
  rate_limited: 'Провайдер просит подождать. Следующий прогон повторит сам.',
  network: 'Источник недоступен. Следующий прогон повторит сам.',
  remote_error: 'Источник ответил ошибкой. Подробности — в логах воркера.',
  not_implemented: 'Адаптера у источника ещё нет.',
};

export const NEVER_POLLED = 'ещё не опрашивали';

/**
 * Состояние источника по тому, что о нём знает сервер, либо `null` — всё в порядке.
 *
 * Адаптера нет — «не подключён», независимо от записанных ошибок: у заготовки их
 * и не бывает. Класс `not_implemented` приводит к тому же состоянию, если сервер
 * знает про адаптер больше экрана.
 */
export function sourceState(source: SignalSource, readable: boolean): SourceState | null {
  if (!readable || source.last_error_class === 'not_implemented') return 'not_connected';
  if (source.last_error_class === 'needs_login') return 'needs_login';
  if (source.last_error_class !== null) return 'broken';
  return null;
}

/**
 * Момент прогона как «25.10 14:03» — с днём.
 *
 * Только часы (`clock`) здесь не годятся: «опрошен в 14:03» без дня читается как
 * «сегодня», а источник мог молчать три дня. Нечитаемый момент отвечает пустой
 * строкой, как и `clock`.
 */
export function moment(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  const two = (value: number) => String(value).padStart(2, '0');
  return `${two(at.getDate())}.${two(at.getMonth() + 1)} ${two(at.getHours())}:${two(at.getMinutes())}`;
}
