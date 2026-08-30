// [review:need-review] PHASE-03/109
// summary: pure helpers of the browser session — the login route, the sanitized `next` round trip, and the rule that decides when a 401 sends the reader to the login page

/**
 * Вход веб-клиента, вычислительная часть.
 *
 * Ключ в браузере не хранится нигде: он вводится на `/login`, уходит телом
 * одного запроса и обменивается на `HttpOnly`-куку (`app/api/auth.py`). Поэтому
 * здесь нет ни чтения `localStorage`, ни заголовка `X-API-Key` — только маршрут
 * входа, возврат на исходный экран и правило «когда 401 уводит на вход».
 *
 * Модуль сознательно чистый: он импортируется и страницей, и клиентом API, а
 * решение об открытом редиректе проверяется тестом, а не глазами.
 */

/** Экран входа. Единственный экран, доступный без сессии. */
export const LOGIN_PATH = '/login';

/** Параметр, в котором логин запоминает, куда читатель шёл. */
export const NEXT_PARAM = 'next';

/** Куда возвращать после входа, когда возвращаться некуда. */
export const DEFAULT_AFTER_LOGIN = '/';

/** Открыт ли сейчас экран входа. */
export function isLoginPath(pathname: string): boolean {
  return pathname === LOGIN_PATH;
}

/**
 * Безопасен ли адрес возврата.
 *
 * Пускаем только путь внутри этого же приложения. `//evil.example` браузер
 * читает как протокол-относительный абсолютный URL, поэтому одной проверки на
 * ведущий слэш мало: без второго условия ссылка `?next=//evil.example` уводила
 * бы человека с введённым только что ключом на чужой сайт.
 */
export function isSafeReturnPath(target: string): boolean {
  return target.startsWith('/') && !target.startsWith('//') && !target.startsWith('/\\');
}

/** Адрес экрана входа, помнящий, куда читатель шёл. */
export function loginHref(from: string): string {
  if (!isSafeReturnPath(from) || isLoginPath(from)) return LOGIN_PATH;
  return `${LOGIN_PATH}?${NEXT_PARAM}=${encodeURIComponent(from)}`;
}

/** Куда уходить после успешного входа: запомненный экран или дашборд. */
export function afterLoginHref(next: string | null): string {
  if (next === null || !isSafeReturnPath(next) || isLoginPath(next)) {
    return DEFAULT_AFTER_LOGIN;
  }
  return next;
}

/**
 * Нужно ли на этот ответ уводить читателя на экран входа.
 *
 * Только 401 и только не с самого экрана входа: там 401 означает «ключ не тот»
 * и обязан остаться сообщением в форме, а не циклом перезагрузок.
 */
export function shouldRedirectToLogin(status: number, pathname: string): boolean {
  return status === 401 && !isLoginPath(pathname);
}

/**
 * Адрес, на который уводит ответ сервера, или `null`, если уводить не надо.
 *
 * Вся развилка «401 с этого экрана → туда-то» собрана здесь одной чистой
 * функцией, чтобы в клиенте API осталось одно ветвление на `null`, а не правило,
 * которое нечем проверить.
 */
export function loginRedirectTarget(
  status: number,
  pathname: string,
  search = ''
): string | null {
  if (!shouldRedirectToLogin(status, pathname)) return null;
  return loginHref(`${pathname}${search}`);
}
