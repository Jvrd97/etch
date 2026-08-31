'use client';
// [review:need-review] PHASE-03/120
// summary: the two signs that a turn is alive — three breathing dots while nothing has been said yet, and a caret at the end of the text while it is still arriving; both fall back to a static mark under prefers-reduced-motion, which lives in globals.css rather than in a media query read by JavaScript

/**
 * Признак жизни идущего хода.
 *
 * Два разных знака, потому что вопрос у человека разный. До первого слова он
 * спрашивает «оно вообще работает» — отвечают точки. Когда текст пошёл, ответ
 * уже виден глазами, и сказать остаётся только «это ещё не конец» — отвечает
 * курсор в конце строки.
 *
 * Оба знака — чистая разметка плюс класс: `prefers-reduced-motion` разбирается
 * в CSS, а не чтением `matchMedia` в компоненте. Настройку меняют посреди
 * сессии, и слушать её здесь означало бы завести подписку на каждый пузырь.
 */

/** Три точки. Одна и та же анимация со сдвигом фазы — не три разных. */
const DOT_DELAYS_MS = [0, 180, 360];

export const WAITING_TESTID = 'turn-waiting';
export const CARET_TESTID = 'turn-caret';

/** Что слышит человек с экранным диктором вместо трёх точек. */
export const WAITING_LABEL = 'Ответ готовится';

export function WaitingDots() {
  return (
    <span
      role="status"
      aria-label={WAITING_LABEL}
      data-testid={WAITING_TESTID}
      className="inline-flex items-center gap-1 py-1 align-middle"
    >
      {DOT_DELAYS_MS.map((delay) => (
        <span key={delay} className="chat-dot" style={{ animationDelay: `${delay}ms` }} />
      ))}
    </span>
  );
}

/**
 * Курсор в конце пришедшего куска.
 *
 * `aria-hidden`: диктор уже читает сам текст, и «конец строки» ему не событие.
 * Незавершённость хода озвучивает состояние экрана, а не эта чёрточка.
 */
export function StreamingCaret() {
  return <span aria-hidden="true" data-testid={CARET_TESTID} className="chat-caret" />;
}
